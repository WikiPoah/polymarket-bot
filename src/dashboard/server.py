"""Minimal read-only HTTP dashboard server."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from src.dashboard.data import DashboardDataBuilder
from src.paper_trading.history import PaperTradingRecorder


HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>PolymarketBot Monitor</title>
<style>body{font:15px system-ui;margin:2rem;background:#f5f7fb;color:#172033}section{background:white;padding:1rem;margin:1rem 0;border-radius:8px;box-shadow:0 1px 4px #ccd}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.5rem;border-bottom:1px solid #e5e7eb}.metric{display:inline-block;margin-right:2rem}.muted{color:#687386}</style>
</head><body><h1>PolymarketBot Monitor</h1><section><h2>Performance Overview</h2><div id="performance"></div></section><section><h2>Current Opportunities</h2><div id="opportunities"></div></section><section><h2>Decision History</h2><div id="history"></div></section>
<script>
const pct = n => (100*n).toFixed(1)+'%';
function table(items, history=false){ if(!items.length)return '<p class="muted">No decisions recorded.</p>'; return '<table><tr><th>Market</th><th>Decision</th><th>Estimated</th><th>Market</th><th>Edge</th><th>Confidence</th><th>Sources</th><th>Risk</th></tr>'+items.map(x=>`<tr><td>${x.market_question||'—'}</td><td>${x.decision}</td><td>${pct(x.estimated_probability)}</td><td>${pct(x.market_probability)}</td><td>${pct(x.edge)}</td><td>${pct(x.confidence)}</td><td>${x.supporting_sources.join(', ')||'—'}</td><td>${x.risk_status}${x.risk_reason?' — '+x.risk_reason:''}</td></tr>`).join('')+'</table>'; }
fetch('/api/dashboard').then(r=>r.json()).then(d=>{let p=d.performance;document.getElementById('performance').innerHTML=`<span class="metric">Decisions: <b>${p.total_decisions}</b></span><span class="metric">Trades: <b>${p.executed_trades}</b></span><span class="metric">Win rate: <b>${pct(p.win_rate)}</b></span><span class="metric">P/L: <b>${p.profit_loss.toFixed(4)}</b></span><span class="metric">Avg edge: <b>${pct(p.average_edge)}</b></span><span class="metric">Avg confidence: <b>${pct(p.average_confidence)}</b></span>`;document.getElementById('opportunities').innerHTML=table(d.current_opportunities);document.getElementById('history').innerHTML=table(d.history,true);}).catch(e=>document.body.insertAdjacentHTML('beforeend','<p>Dashboard data unavailable.</p>'));
</script></body></html>"""


def create_server(
    builder: DashboardDataBuilder | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> ThreadingHTTPServer:
    builder = builder or DashboardDataBuilder()

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/dashboard":
                body = json.dumps(builder.build()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            elif path in {"/", "/index.html"}:
                body = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            else:
                body = b"Not found"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    return ThreadingHTTPServer((host, port), DashboardHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the paper-trading dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--history", default="data/paper_trading_history.json")
    args = parser.parse_args()
    builder = DashboardDataBuilder(PaperTradingRecorder(args.history))
    server = create_server(builder, args.host, args.port)
    print(f"Dashboard listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
