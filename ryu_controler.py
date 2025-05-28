from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4
from ryu.lib import hub
from collections import defaultdict
import time

from ryu.app.wsgi import WSGIApplication, ControllerBase, route
from webob import Response
import json

# Tên của controller trong WSGI
SDN_LB_INSTANCE_NAME = 'sdn_lb_api_app'
MAX_CLIENTS_PER_AP = 3  # Giới hạn số lượng client trên mỗi AP

class SDNWiFiLoadBalancer(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(SDNWiFiLoadBalancer, self).__init__(*args, **kwargs)
        wsgi = kwargs['wsgi']
        wsgi.register(SDNLBRestAPI, {SDN_LB_INSTANCE_NAME: self})

        # Cấu trúc lưu trữ trạng thái mạng
        self.mac_to_port = defaultdict(dict)  # MAC → cổng (trên từng AP)
        self.mac_to_ip = {}  # MAC → IP
        self.client_count = defaultdict(int)  # Số client kết nối trên mỗi AP
        self.last_seen = defaultdict(dict)  # Thời gian cuối cùng mỗi MAC gửi gói tin
        self.active_switches = set()  # Danh sách AP đang hoạt động
        self.switch_connect_time = {}  # Thời điểm switch kết nối vào mạng
        self.dpid_to_ip = {}  # Gán IP đại diện cho từng DPID
        self.port_stats = defaultdict(dict)  # Thống kê lưu lượng trên từng cổng
        self.datapaths = {}  # Lưu các datapath object
        self.mac_rssi = {}  # RSSI giả lập cho từng MAC
        self.faulty_aps = set()  # Tập hợp các AP bị coi là lỗi
        self.prev_port_stats = defaultdict(dict)  # Thống kê cũ để phát hiện lỗi
        self.roaming_events = []  # Lưu lịch sử chuyển AP

        # Bắt đầu luồng giám sát
        self.monitor_thread = hub.spawn(self._monitor)

    # Hàm giám sát định kỳ
    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            self._detect_ap_failure()
            self._cleanup_stale_hosts()
            self.check_rssi_and_roam()  # Gọi kiểm tra roaming theo RSSI
            hub.sleep(5)

    def _request_stats(self, datapath):
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto_v1_3.OFPP_ANY)
        datapath.send_msg(req)

    # Phát hiện AP không có lưu lượng thay đổi → coi là lỗi
    def _detect_ap_failure(self):
        for dpid in self.port_stats:
            unchanged = True
            for port_no, stats in self.port_stats[dpid].items():
                prev = self.prev_port_stats[dpid].get(port_no, {})
                if stats.get('rx_bytes') != prev.get('rx_bytes') or stats.get('tx_bytes') != prev.get('tx_bytes'):
                    unchanged = False
                    break
            if unchanged:
                self.faulty_aps.add(dpid)
            else:
                self.faulty_aps.discard(dpid)
            self.prev_port_stats[dpid] = dict(self.port_stats[dpid])

    # Loại bỏ các host không gửi gói tin trong 60 giây
    def _cleanup_stale_hosts(self):
        now = time.time()
        timeout = 60
        for dpid in list(self.mac_to_port.keys()):
            self.mac_to_port[dpid] = {
                mac: port for mac, port in self.mac_to_port[dpid].items()
                if now - self.last_seen[dpid].get(mac, 0) < timeout
            }
            self.client_count[dpid] = len(self.mac_to_port[dpid])

    # Kiểm tra RSSI của các client, nếu thấp thì thực hiện chuyển AP
    def check_rssi_and_roam(self):
        RSSI_THRESHOLD = -57 # Ngưỡng RSSI thấp để chuyển AP
        for dpid in self.active_switches:
            for mac in list(self.mac_to_port[dpid].keys()):
                rssi = self.mac_rssi.get(mac, -100)
                if rssi < RSSI_THRESHOLD or dpid in self.faulty_aps:
                    alt_ap = self.find_least_loaded_ap(exclude_dpid=dpid)
                    if alt_ap and alt_ap != dpid:
                        self.logger.info(f"Roaming {mac} from AP {dpid} to AP {alt_ap} due to {'low RSSI' if rssi < RSSI_THRESHOLD else 'faulty AP'}")
                        self.mac_to_port[dpid].pop(mac, None)  # Xóa khỏi AP cũ
                        self.client_count[dpid] -= 1
                        out_port = 1
                        self.mac_to_port[alt_ap][mac] = out_port  # Gán sang AP mới
                        self.client_count[alt_ap] = len(self.mac_to_port[alt_ap])
                        match = self.datapaths[alt_ap].ofproto_parser.OFPMatch(eth_src=mac)
                        actions = [self.datapaths[alt_ap].ofproto_parser.OFPActionOutput(out_port)]
                        self.add_flow(self.datapaths[alt_ap], 1, match, actions)  # Tạo flow mới
                        self.roaming_events.append({
                            "mac": mac,
                            "from_ap": dpid,
                            "to_ap": alt_ap,
                            "reason": "low_rssi" if rssi < RSSI_THRESHOLD else "ap_failure",
                            "rssi": rssi,
                            "time": time.time()
                        })

    # Khi switch kết nối lần đầu → gán flow mặc định và ghi nhận thông tin
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        dpid = datapath.id
        self.active_switches.add(dpid)
        self.switch_connect_time[dpid] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        self.datapaths[dpid] = datapath
        self.dpid_to_ip[dpid] = f"192.168.0.{dpid}"
        self.logger.info(f"Switch {dpid} connected at {self.switch_connect_time[dpid]}")

    # Khi switch ngắt kết nối → loại khỏi danh sách
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def switch_state_change_handler(self, ev):
        datapath = ev.datapath
        if datapath is None:
            return
        dpid = datapath.id
        if ev.state == DEAD_DISPATCHER:
            self.active_switches.discard(dpid)
            self.mac_to_port.pop(dpid, None)
            self.client_count.pop(dpid, None)
            self.last_seen.pop(dpid, None)
            self.switch_connect_time.pop(dpid, None)
            self.dpid_to_ip.pop(dpid, None)
            self.datapaths.pop(dpid, None)
            self.faulty_aps.discard(dpid)
            self.logger.warning(f"Switch {dpid} disconnected")

    # Nhận thống kê lưu lượng từ switch
    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        self.port_stats[dpid] = {}
        for stat in ev.msg.body:
            self.port_stats[dpid][stat.port_no] = {
                'rx_bytes': stat.rx_bytes,
                'tx_bytes': stat.tx_bytes
            }

    # Thêm flow vào bảng định tuyến của switch
    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority, match=match, instructions=inst)
        datapath.send_msg(mod)

    # Tìm AP đang hoạt động có ít client nhất
    def find_least_loaded_ap(self, exclude_dpid=None):
        best_ap = None
        min_clients = float('inf')
        for dpid in self.active_switches:
            if dpid == exclude_dpid or dpid in self.faulty_aps:
                continue
            count = self.client_count.get(dpid, 0)
            if count < min_clients and count < MAX_CLIENTS_PER_AP:
                min_clients = count
                best_ap = dpid
        return best_ap

    # Hàm xử lý gói tin đầu vào từ AP
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == 0x88cc:
            return  # Bỏ qua LLDP

        dst = eth.dst
        src = eth.src
        in_port = msg.match['in_port']

        # Ghi nhận địa chỉ IP từ gói ARP hoặc IPv4
        pkt_arp = pkt.get_protocol(arp.arp)
        pkt_ip = pkt.get_protocol(ipv4.ipv4)
        if pkt_arp and pkt_arp.src_ip:
            self.mac_to_ip[pkt_arp.src_mac] = pkt_arp.src_ip
        elif pkt_ip:
            self.mac_to_ip[src] = pkt_ip.src

        # Nếu AP đã đầy → chuyển hướng sang AP khác
        if src not in self.mac_to_port[dpid]:
            if self.client_count[dpid] >= MAX_CLIENTS_PER_AP:
                alt_ap = self.find_least_loaded_ap(exclude_dpid=dpid)
                if alt_ap:
                    self.logger.info(f"Redirecting {src} from AP {dpid} to AP {alt_ap}")
                    for ap in list(self.mac_to_port):
                        self.mac_to_port[ap].pop(src, None)
                        self.client_count[ap] = len(self.mac_to_port[ap])
                    out_port = 1
                    self.mac_to_port[alt_ap][src] = out_port
                    self.client_count[alt_ap] = len(self.mac_to_port[alt_ap])
                    match = self.datapaths[alt_ap].ofproto_parser.OFPMatch(eth_src=src)
                    actions = [self.datapaths[alt_ap].ofproto_parser.OFPActionOutput(out_port)]
                    self.add_flow(self.datapaths[alt_ap], 1, match, actions)
                else:
                    self.logger.warning(f"No available AP for {src}, dropping connection")
                return
            
        # Cập nhật bảng MAC → port
        self.mac_to_port[dpid][src] = in_port
        self.last_seen[dpid][src] = time.time()
        self.client_count[dpid] = len(self.mac_to_port[dpid])

        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self.add_flow(datapath, 1, match, actions)

        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id,
            in_port=in_port, actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        )
        datapath.send_msg(out)

# REST API cung cấp trạng thái hệ thống
class SDNLBRestAPI(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(SDNLBRestAPI, self).__init__(req, link, data, **config)
        self.sdn_app = data[SDN_LB_INSTANCE_NAME]

    # Trả về thông tin tải từng AP
    @route('load_status', '/load_status', methods=['GET'])
    def get_ap_load(self, req, **kwargs):
        status = {
            str(dpid): {
                "ip": self.sdn_app.dpid_to_ip.get(dpid, "N/A"),
                "clients": self.sdn_app.client_count.get(dpid, 0),
                "last_seen": self.sdn_app.switch_connect_time.get(dpid, "unknown"),
                "mac_table": list(self.sdn_app.mac_to_port[dpid].keys()),
                "port_stats": self.sdn_app.port_stats.get(dpid, {}),
                "is_faulty": dpid in self.sdn_app.faulty_aps
            }
            for dpid in self.sdn_app.active_switches
        }
        return Response(content_type='application/json', text=json.dumps(status))

    # Trả về danh sách client (host) đang kết nối
    @route('host_status', '/host_status', methods=['GET'])
    def get_host_status(self, req, **kwargs):
        host_info = []
        for dpid in self.sdn_app.active_switches:
            for mac, port in self.sdn_app.mac_to_port.get(dpid, {}).items():
                stats = self.sdn_app.port_stats[dpid].get(port, {})
                host_info.append({
                    "mac": mac,
                    "ip": self.sdn_app.mac_to_ip.get(mac, "N/A"),
                    "ap": dpid,
                    "port": port,
                    "rx_bytes": stats.get('rx_bytes', 0),
                    "tx_bytes": stats.get('tx_bytes', 0),
                    "rssi": self.sdn_app.mac_rssi.get(mac, -100)
                })
        return Response(content_type='application/json', text=json.dumps(host_info))

    # API nhận dữ liệu RSSI từ station gửi về
    @route('update_rssi', '/update_rssi', methods=['POST'])
    def update_rssi(self, req, **kwargs):
        data = json.loads(req.body)
        mac = data.get('mac')
        rssi = data.get('rssi')
        self.sdn_app.mac_rssi[mac] = rssi
        return Response(text="OK", status=200)

    # Trả về các số liệu hiệu năng của toàn hệ thống
    @route('performance_metrics', '/performance_metrics', methods=['GET'])
    def get_metrics(self, req, **kwargs):
        metrics = {
            "total_clients": sum(self.sdn_app.client_count.values()),
            "ap_load": dict(self.sdn_app.client_count),
            "faulty_aps": list(self.sdn_app.faulty_aps),
            "roaming_events": self.sdn_app.roaming_events[-10:]
        }
        return Response(content_type='application/json', text=json.dumps(metrics))
