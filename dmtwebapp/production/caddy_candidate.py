#!/usr/bin/env python3
"""Generate a candidate Caddyfile without printing unrelated config or secrets."""
import sys
from pathlib import Path
p=Path(sys.argv[1]);out=Path(sys.argv[2]);text=p.read_text()
old='jsaiclass.duckdns.org {\n\treverse_proxy 127.0.0.1:31007\n}'
if text.count(old)!=1:raise SystemExit('existing jsaiclass route differs; review required')
if text.lstrip().startswith('{') or 'on_demand_tls' in text or '\nhttps:// {' in text:raise SystemExit('existing global TLS policy; review required')
new='''jsaiclass.duckdns.org {
 @dmt path /dmtwebapp /dmtwebapp/*
 handle /dmtwebapp/trial/* {
  reverse_proxy 127.0.0.1:31007
 }
 handle @dmt {
  reverse_proxy 127.0.0.1:31107
 }
 handle {
  reverse_proxy 127.0.0.1:31007
 }
}'''
# Replace only exact site block. Explicit existing hosts retain priority.
text=text.replace(old,new)
global_options='''{
 on_demand_tls {
  ask http://127.0.0.1:31107/internal/tls
 }
}
'''
catchall=r'''
https:// {
 tls {
  on_demand
 }
 @dmt host_regexp dmt "^dmt-[0-9a-f]{32}\.jsaiclass\.duckdns\.org$"
 handle @dmt {
  reverse_proxy 127.0.0.1:31107
 }
 handle {
  respond 404
 }
}
'''
# Handle only this project on HTTP; other existing :80 routes remain untouched.
needle=':80 {\n'
if text.count(needle)!=1:raise SystemExit('existing HTTP fallback differs')
text=text.replace(needle,needle+r''' @dmt_http host_regexp dmt_http "^dmt-[0-9a-f]{32}\.jsaiclass\.duckdns\.org$"
 redir @dmt_http https://{host}{uri} 308
''')
out.write_text(global_options+'\n'+text+catchall)
