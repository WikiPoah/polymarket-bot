# File-Version: 1.2.0
"""Minimal read-only HTTP dashboard server."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from src.dashboard.data import DashboardDataBuilder
from src.paper_trading.history import PaperTradingRecorder


HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>PolymarketBot Monitor</title>
<style>body{font:15px system-ui;margin:2rem;background:#f5f7fb;color:#172033}section,details{background:white;padding:1rem;margin:1rem 0;border-radius:8px;box-shadow:0 1px 4px #ccd}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:.5rem;border-bottom:1px solid #e5e7eb}.metric{display:inline-block;margin:0 2rem .5rem 0}.accepted{color:#087443}.rejected{color:#a33131}.muted{color:#687386}.rationale{min-width:18rem}summary{cursor:pointer;font-weight:600}</style>
</head><body><h1>PolymarketBot Decision Review</h1><p class="muted">Paper-trading analysis only. Accepted ideas are unresolved unless marked settled.</p><section><h2>Decision Funnel</h2><div id="funnel"></div></section><section><h2>Accepted Paper-Trade Ideas</h2><p class="muted">Opportunities that passed strategy and portfolio-risk checks.</p><div id="accepted"></div></section><section><h2>Outcome Tracking</h2><div id="performance"></div></section><section><h2>System Health</h2><div id="system"></div></section><section><h2>Recent Activity</h2><div id="activity"></div></section><details><summary>Inspect ignored and risk-rejected decisions</summary><h3>Risk rejected</h3><div id="rejected"></div><h3>Ignored by strategy</h3><div id="ignored"></div></details>
<script>
const pct = n => (100*n).toFixed(1)+'%';
const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
function table(items, empty='No decisions recorded.'){ if(!items.length)return `<p class="muted">${esc(empty)}</p>`; return '<table><tr><th>Market</th><th>Action</th><th>Bot</th><th>Market</th><th>Edge</th><th>Confidence</th><th>Catalyst and sources</th><th>Rationale</th></tr>'+items.map(x=>`<tr><td>${esc(x.market_question||'—')}</td><td>${esc(x.decision)}</td><td>${pct(x.estimated_probability)}</td><td>${pct(x.market_probability)}</td><td>${pct(x.edge)}</td><td>${pct(x.confidence)}</td><td>${esc(x.event_title||'—')}<br><span class="muted">${esc(x.supporting_sources.join(', ')||'No supporting sources')}</span></td><td class="rationale">${esc(x.rationale)}</td></tr>`).join('')+'</table>'; }
fetch('/api/dashboard').then(r=>r.json()).then(d=>{let p=d.performance,f=d.decision_funnel,s=d.system,l=s.latest_run,providers=Object.entries(s.provider_freshness).map(([k,v])=>`${esc(k)}: ${esc(v.status)}, data ${esc(v.last_data_received||'never')}, age ${v.event_age_seconds==null?'unknown':Math.round(v.event_age_seconds)+'s'}`).join('<br>')||'None';document.getElementById('funnel').innerHTML=`<span class="metric">Evaluated: <b>${f.evaluated}</b></span><span class="metric accepted">Accepted: <b>${f.accepted}</b></span><span class="metric rejected">Risk rejected: <b>${f.risk_rejected}</b></span><span class="metric">Ignored: <b>${f.ignored}</b></span><span class="metric">Settled: <b>${f.settled}</b></span>`;document.getElementById('accepted').innerHTML=table(d.accepted_trade_ideas,'No opportunities passed the current thresholds.');document.getElementById('rejected').innerHTML=table(d.rejected_decisions,'No decisions were rejected by portfolio risk.');document.getElementById('ignored').innerHTML=table(d.ignored_decisions,'No decisions were ignored.');document.getElementById('activity').innerHTML=table(d.recent_activity);document.getElementById('system').innerHTML=`<span class="metric">Health: <b>${esc(s.health)}</b></span><span class="metric">Data freshness: <b>${esc(s.data_freshness||'Never')}</b></span><span class="metric">Run: <b>${esc(l?l.run_id:'None')}</b></span><span class="metric">Markets: <b>${l?l.markets_analyzed:0}</b></span><span class="metric">Last decisions: <b>${l?l.decisions_generated:0}</b></span><p>Providers:<br><b>${providers}</b></p>`;document.getElementById('performance').innerHTML=`<span class="metric">Accepted trades: <b>${p.executed_trades}</b></span><span class="metric">Settled wins/losses: <b>${p.wins}/${p.losses}</b></span><span class="metric">Win rate: <b>${f.settled?pct(p.win_rate):'Not available'}</b></span><span class="metric">Settled P/L: <b>${p.profit_loss.toFixed(4)}</b></span>`;}).catch(e=>document.body.insertAdjacentHTML('beforeend','<p>Dashboard data unavailable.</p>'));
</script></body></html>"""


def create_server(
    builder: DashboardDataBuilder | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> ThreadingHTTPServer:
    builder = builder or DashboardDataBuilder()

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "PolymarketDashboard"
        sys_version = ""

        def version_string(self) -> str:
            return self.server_version

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
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; connect-src 'self'; "
                "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
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
