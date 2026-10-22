#!/usr/bin/env bash
# اجرای همهٔ تست‌ها.
# دو سرور همراه خودکار با پایگاه داده‌ی تازه بالا می‌آیند:
#   ۸۰۸۱: زمان‌بندی واقعی، اپ‌ها و API (حالت توسعه)
#   ۸۰۸۲: زمان‌بندی فشرده (HZ_TIME_SCALE=0.01) برای تست انقضا
# سرور مسافر جدا نیست؛ همه‌چیز از همان سرور سرو می‌شود.
set -u
cd "$(dirname "$0")"
TESTS_DIR="$(pwd)"
SERVER_DIR="$(cd ../server && pwd)"
for port in 8081 8082; do
  if curl -s -o /dev/null "http://127.0.0.1:$port/api/config"; then echo "پورت $port از قبل اشغال است؛ سرور قبلی را ببندید."; exit 2; fi
done
DB_TMP="$(mktemp -u /tmp/hz_run_XXXX).sqlite"
DB_FAST="$(mktemp -u /tmp/hz_fast_XXXX).sqlite"
(cd "$SERVER_DIR" && exec env HZ_DEV=1 HZ_ADMIN_PASSWORD=test-admin-pass HZ_DB="$DB_TMP" PORT=8081 node server.js > "$TESTS_DIR/assets/last_server.log" 2>&1) &
SERVER_PID=$!
(cd "$SERVER_DIR" && exec env HZ_DEV=1 HZ_TIME_SCALE=0.01 HZ_DB="$DB_FAST" PORT=8082 node server.js > "$TESTS_DIR/assets/last_server_fast.log" 2>&1) &
FAST_PID=$!
trap 'kill $SERVER_PID $FAST_PID 2>/dev/null; sleep 0.5; rm -f "$DB_TMP" "$DB_TMP-wal" "$DB_TMP-shm" "$DB_FAST" "$DB_FAST-wal" "$DB_FAST-shm"' EXIT
for port in 8081 8082; do
  for i in $(seq 1 20); do curl -s -o /dev/null "http://127.0.0.1:$port/api/config" && break; sleep 0.5; done
  if ! curl -s -o /dev/null "http://127.0.0.1:$port/api/config"; then echo "سرور پورت $port بالا نیامد"; exit 2; fi
done

python3 mkpng.py >/dev/null
fail=0
run() { echo "== $*"; if timeout 300 "$@" > "assets/last_$(echo "$*" | tr ' /' '__').log" 2>&1; then echo "   ok"; else echo "   FAILED (see assets/)"; fail=1; fi; }
run node "$SERVER_DIR/test/sms.test.js"
run env BASE=http://127.0.0.1:8081 node "$SERVER_DIR/test/api.test.js"
run env BASE=http://127.0.0.1:8081 node "$SERVER_DIR/test/features_cities_security.test.js"
run env BASE=http://127.0.0.1:8082 node "$SERVER_DIR/test/timing.test.js"
run python3 traveler_convert_ui.py http://127.0.0.1:8082
run python3 cross_app_e2e.py
run python3 traveler_change_ui.py
run python3 traveler_cancel_ui.py
run python3 traveler_pay_ui.py
run python3 traveler_settle_ui.py
run python3 traveler_invoice_ui.py
run python3 translator_pay_ui.py
run python3 admin_ui.py
run python3 admin_docs_ui.py
run python3 admin_slots_ui.py
run python3 admin_editors_ui.py
run python3 tariff_browser_ui.py http://127.0.0.1:8081
run python3 admin_system_ui.py http://127.0.0.1:8081
run python3 features_ui.py http://127.0.0.1:8081 test-admin-pass
run python3 service_actions_ui.py
run python3 booking_actions_ui.py
run python3 account_delete_ui.py
run python3 traveler_support_ui.py
run python3 account_truth_ui.py
run python3 logout_sessions_ui.py
run python3 traveler_auth_ui.py
run python3 login_flow.py fa
run python3 login_flow.py en
run python3 login_flow.py ar
run python3 spec_audit.py
run python3 bk_flow.py ar
run python3 photo_flow.py fa
run python3 tr_e2e_full.py 390
run python3 tr_missions_ui.py
run python3 tr_daybar.py
run python3 tr_testapprove.py
run python3 tr_docs_ui.py
run python3 tr_live_docs_ui.py
run python3 tr_docs_send_ui.py
run python3 tr_interview_ui.py
run python3 map_real.py
run python3 map_search_ui.py
run python3 no_sim_buttons.py
run python3 extension_ui.py
run python3 finish_flow_ui.py
run python3 booking_options_ui.py
run python3 service_clock_ui.py
run python3 payment_methods_ui.py
run python3 settlement_failure_ui.py
exit $fail
