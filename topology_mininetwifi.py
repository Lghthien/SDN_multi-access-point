from mininet.log import setLogLevel, info
from mn_wifi.net import Mininet_wifi
from mn_wifi.cli import CLI
from mn_wifi.node import OVSKernelAP
from mn_wifi.link import wmediumd
from mn_wifi.wmediumdConnector import interference
from mininet.node import RemoteController
from threading import Thread, Event
import requests
import time

# Cờ dừng toàn cục
stop_event = Event()

def send_rssi_updates(stations, controller_ip='127.0.0.1:8080'):
    while not stop_event.is_set():
        for sta in stations:
            try:
                sta_index = int(sta.name[3:])
                mac = sta.MAC()
                rssi = -60 + (sta_index % 3) * 5
                res = requests.post(f"http://{controller_ip}/update_rssi",
                                    json={"mac": mac, "rssi": rssi}, timeout=2)
                if res.status_code != 200:
                    print(f"[WARN] RSSI update failed for {mac}: {res.status_code}")
            except Exception as e:
                print(f"[ERROR] Failed to send RSSI for {sta.name}: {e}")
        stop_event.wait(5)

def generate_continuous_traffic(stations, interval=5):
    """
    Gửi ping liên tục giữa các station bằng cách dùng cmdBackground để tránh poll() conflict
    """
    def run():
        while not stop_event.is_set():
            for i in range(len(stations)):
                for j in range(i + 1, len(stations)):
                    sta_src = stations[i]
                    sta_dst = stations[j]
                    sta_src.cmdBackground(f'ping -c1 -W1 {sta_dst.IP()}')
            time.sleep(interval)
    Thread(target=run, daemon=True).start()

def pause_ap_cli(net, ap_name='ap_pool', down_time=15):
    ap = net.get(ap_name)
    def run():
        print(f"\n[CLI DEMO] Tạm dừng {ap.name} trong {down_time} giây...\n")
        ap.cmd(f'ifconfig {ap.name}-wlan1 down')
        time.sleep(down_time)
        print(f"\n[CLI DEMO] Bật lại {ap.name}\n")
        ap.cmd(f'ifconfig {ap.name}-wlan1 up')
    Thread(target=run, daemon=True).start()

def resort_topology():
    net = Mininet_wifi(controller=RemoteController, accessPoint=OVSKernelAP,
                       link=wmediumd, wmediumd_mode=interference)

    info("*** Thêm controller\n")
    c0 = net.addController('c0', controller=RemoteController,
                           ip='127.0.0.1', port=6653)

    info("*** Thêm Access Point\n")
    ap1 = net.addAccessPoint('ap_lobby', dpid='0000000000000001',
                             ssid='LobbyAP', mode='g', channel='1',
                             position='20,50,0', range=35)
    ap2 = net.addAccessPoint('ap_pool', dpid='0000000000000002',
                             ssid='PoolAP', mode='g', channel='6',
                             position='50,50,0', range=35)
    ap3 = net.addAccessPoint('ap_conf', dpid='0000000000000003',
                             ssid='ConfAP', mode='g', channel='11',
                             position='80,50,0', range=35)

    ap1.name_display = 'AP 1 - Lobby'
    ap2.name_display = 'AP 2 - Pool'
    ap3.name_display = 'AP 3 - Conference'

    info("*** Thêm Stations\n")
    stations = []
    positions = [
        '5,50,0',     # sta1 – chỉ AP1
        '50,15,0',    # sta2 – chỉ AP2
        '95,50,0',    # sta3 – chỉ AP3
        '35,50,0',    # sta4 – AP1 & AP2
        '65,50,0',    # sta5 – AP2 & AP3
        '35,65,0',    # sta6 – AP1 & AP3
        '50,50,0',    # sta7 – cả 3 AP
        '50,53,0'     # sta8 – cả 3 AP
    ]
    for i in range(8):
        sta = net.addStation(f'sta{i+1}', ip=f'10.0.0.{i+1}/8', position=positions[i])
        stations.append(sta)

    info("*** Cấu hình WiFi\n")
    net.configureWifiNodes()

    info("*** Khởi động mạng\n")
    net.build()
    c0.start()
    for ap in [ap1, ap2, ap3]:
        ap.start([c0])

    info("*** Bắt đầu cập nhật RSSI và gửi ping liên tục\n")
    Thread(target=send_rssi_updates, args=(stations,), daemon=True).start()
    generate_continuous_traffic(stations)
    net.pause_ap_cli = pause_ap_cli
    info("*** CLI tương tác\n")
    try:
        CLI(net)
    finally:
        stop_event.set()
        net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    resort_topology()
