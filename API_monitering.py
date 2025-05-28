from flask import Flask, render_template_string, jsonify
import requests

app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <title>SDN AP Monitor</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    table { width: 100%; border-collapse: collapse; margin-top: 20px; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
    th { background-color: #f0f0f0; }
    tr.faulty { background-color: #ffe0e0; color: red; font-weight: bold; }
    .section { margin-bottom: 40px; }
  </style>
</head>
<body>

  <div class="section">
    <h2>📡 Trạng thái chi tiết từng AP</h2>
    <p><i>Lần cập nhật: <span id="lastUpdated">--</span></i></p>
    <table id="apTable">
      <thead><tr>
        <th>AP ID</th><th>Địa chỉ IP</th><th>Thời gian kết nối</th>
        <th>Số Client</th><th>MAC Clients</th><th>Rx Bytes</th><th>Tx Bytes</th><th>Faulty</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="section">
    <h3>📊 Biểu đồ số client theo AP</h3>
    <canvas id="apChart" width="800" height="350"></canvas>
  </div>

  <div class="section">
    <h3>🔍 Tài nguyên sử dụng của từng host</h3>
    <table id="hostTable">
      <thead><tr>
        <th>MAC Host</th><th>IP Host</th><th>AP (DPID)</th>
        <th>Port</th><th>Rx Bytes</th><th>Tx Bytes</th><th>RSSI</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="section">
    <h3>📈 Đánh giá hiệu suất hệ thống</h3>
    <ul id="perfMetrics"></ul>
  </div>

  <script>
    const chart = new Chart(document.getElementById('apChart').getContext('2d'), {
      type: 'bar',
      data: {
        labels: [],
        datasets: [{ label: 'Số Client kết nối', data: [], backgroundColor: 'rgba(75,192,192,0.6)' }]
      },
      options: { scales: { y: { beginAtZero: true } } }
    });

    function fetchData() {
      fetch('/api/full_status')
        .then(res => res.json())
        .then(data => {
          if (data.error) throw new Error(data.error);

          const load = data.load;
          const host = data.host;
          const perf = data.perf;

          document.getElementById('lastUpdated').textContent = new Date().toLocaleString();

          // AP Table
          const labels = [], values = [];
          const apTbody = document.querySelector('#apTable tbody');
          apTbody.innerHTML = '';
          for (const [dpid, info] of Object.entries(load)) {
            labels.push('AP ' + dpid);
            values.push(info.clients);
            const row = document.createElement('tr');
            const rx = Object.values(info.port_stats).reduce((s, p) => s + (p.rx_bytes || 0), 0);
            const tx = Object.values(info.port_stats).reduce((s, p) => s + (p.tx_bytes || 0), 0);
            row.innerHTML = `
              <td>AP ${dpid}</td><td>${info.ip}</td><td>${info.last_seen}</td>
              <td>${info.clients}</td><td>${info.mac_table.join('<br>')}</td>
              <td>${rx.toLocaleString()} bytes</td><td>${tx.toLocaleString()} bytes</td>
              <td>${info.is_faulty ? '⚠️' : ''}</td>
            `;
            if (info.is_faulty) row.classList.add('faulty');
            apTbody.appendChild(row);
          }

          chart.data.labels = labels;
          chart.data.datasets[0].data = values;
          chart.update();

          // Host Table
          const hostTbody = document.querySelector('#hostTable tbody');
          hostTbody.innerHTML = '';
          host.forEach(h => {
            const row = document.createElement('tr');
            row.innerHTML = `
              <td>${h.mac}</td><td>${h.ip}</td><td>${h.ap}</td>
              <td>${h.port}</td><td>${h.rx_bytes.toLocaleString()} bytes</td>
              <td>${h.tx_bytes.toLocaleString()} bytes</td><td>${h.rssi}</td>
            `;
            hostTbody.appendChild(row);
          });

          // Performance Metrics
          const perfList = document.querySelector('#perfMetrics');
          perfList.innerHTML = `
            <li>Tổng số client: <b>${perf.total_clients}</b></li>
            <li>AP lỗi: <b>${perf.faulty_aps.join(', ') || 'Không có'}</b></li>
            <li>Sự kiện roaming gần nhất:</li>
            ${perf.roaming_events.map(ev =>
              `<li>${ev.mac} chuyển từ AP ${ev.from_ap} sang AP ${ev.to_ap} lúc ${new Date(ev.time * 1000).toLocaleTimeString()}</li>`
            ).join('')}
          `;
        })
        .catch(err => {
          alert("⚠️ Không thể tải dữ liệu từ controller: " + err.message);
        });
    }

    fetchData();
    setInterval(fetchData, 2000);
  </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/full_status')
def api_full_status():
    try:
        load = requests.get('http://localhost:8080/load_status').json()
        host = requests.get('http://localhost:8080/host_status').json()
        perf = requests.get('http://localhost:8080/performance_metrics').json()
        return jsonify({"load": load, "host": host, "perf": perf})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
