from types import SimpleNamespace

from flask import Flask, jsonify, redirect, render_template, request, url_for


app = Flask(__name__)
app.secret_key = "preview"


@app.context_processor
def inject_globals():
    return {
        "current": SimpleNamespace(tg_id=100000001, role="main_admin", is_admin=True, is_main_admin=True),
        "settings": SimpleNamespace(
            support_link="https://t.me/example_support",
            telegram_proxy_url="socks5h://127.0.0.1:9050",
            card_num="0000-0000-0000-0000",
            referral_percent=20,
            referral_rate=500,
            bot_domain="https://example.com",
            main_admin_chat_ids=[100000001],
            admin_chat_ids=[100000001],
            payment_channel_chat_id="",
            xui_two_factor_code="",
            channels=["@example"],
            ranges=[50, 100, 500],
            prices=[2000, 1800, 1500, 1200],
        ),
        "bot_domain": "https://example.com",
    }


@app.route("/")
def dashboard():
    user = SimpleNamespace(balance=125)
    subscriptions = [
        {
            "subscription": SimpleNamespace(
                name="office_main",
                link="office_main_ab12cd34",
                gigabytes=80,
                is_active=True,
            ),
            "traffic_ok": True,
            "up": 4.25,
            "down": 32.8,
            "remain": 42.95,
        },
        {
            "subscription": SimpleNamespace(
                name="mobile_backup",
                link="mobile_backup_ef56gh78",
                gigabytes=30,
                is_active=False,
            ),
            "traffic_ok": True,
            "up": 2.1,
            "down": 30.7,
            "remain": 0,
        },
    ]
    waitlist = [SimpleNamespace(gigabytes=50, price=100000, message="رسید تست")]
    return render_template("web_panel.html", view="dashboard", user=user, subscriptions=subscriptions, waitlist=waitlist)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        tg_id = request.form.get("tg_id", "").strip()
        if tg_id == "100000001":
            return redirect(url_for("admin"))
        return redirect(url_for("dashboard"))
    return render_template("web_panel_login.html")


@app.route("/admin")
def admin():
    users = [
        SimpleNamespace(tg_id=100000001, balance=125, purchases=20, subscriptions=[1, 2]),
        SimpleNamespace(tg_id=100000002, balance=40, purchases=0, subscriptions=[1]),
    ]
    waitlist = [SimpleNamespace(id=1, user_id=987654321, gigabytes=50, price=100000, message="رسید تست")]
    servers = [
        SimpleNamespace(
            id=1,
            domain="http://1.1.1.1:3000",
            country="DE",
            is_vless=True,
            is_tcp=True,
            protocol="vless",
            network="grpc",
            security="reality",
            port=443,
            inbound_id=7,
        )
    ]
    server_status = {
        1: {
            "ok": True,
            "cpu": 37,
            "mem_current": 2.8,
            "mem_total": 8.0,
            "mem_percent": 35,
            "disk_current": 48.5,
            "disk_total": 120.0,
            "disk_percent": 40,
            "net_up": 0.014,
            "net_down": 0.082,
            "traffic_up": 812.4,
            "traffic_down": 2450.7,
            "xray_state": True,
            "xray_version": "25.1.1",
            "auto_restart_enabled": True,
            "auto_restart_threshold": 90,
            "auto_restart_waiting": False,
            "auto_restart_triggered": False,
        }
    }
    return render_template(
        "web_panel.html",
        view="admin",
        users=users,
        waitlist=waitlist,
        servers=servers,
        server_status=server_status,
        all_subscriptions=[],
        bot_sales_enabled=True,
        available_stats=[("May", "2026"), ("April", "2026")],
    )


@app.get("/admin/servers/status.json")
def admin_server_status_json():
    return jsonify({
        "ok": True,
        "servers": {
            "1": {
                "ok": True,
                "cpu": 42,
                "mem_current": 3.1,
                "mem_total": 8.0,
                "mem_percent": 39,
                "disk_current": 50.2,
                "disk_total": 120.0,
                "disk_percent": 42,
                "net_up": 0.02,
                "net_down": 0.12,
                "traffic_up": 820.4,
                "traffic_down": 2500.7,
                "xray_state": True,
                "xray_version": "26.4.17",
            }
        },
    })


@app.route("/logout")
def logout():
    return redirect(url_for("login"))


@app.post("/subscriptions/create")
def create_subscription_route():
    return redirect(url_for("dashboard"))


@app.post("/subscriptions/extend")
def extend_subscription_route():
    return redirect(url_for("dashboard"))


@app.post("/subscriptions/delete")
def delete_subscription_route():
    return redirect(url_for("dashboard"))


@app.post("/balance/transfer")
def transfer_route():
    return redirect(url_for("dashboard"))


@app.post("/balance/charge")
def charge_route():
    return redirect(url_for("dashboard"))


@app.post("/admin/waitlist/<int:waitlist_id>/approve")
def approve_waitlist_route(waitlist_id):
    return redirect(url_for("admin"))


@app.post("/admin/waitlist/<int:waitlist_id>/deny")
def deny_waitlist_route(waitlist_id):
    return redirect(url_for("admin"))


@app.post("/admin/users/balance")
def admin_set_balance():
    return redirect(url_for("admin"))


@app.post("/admin/servers/add")
def admin_add_server():
    return redirect(url_for("admin"))


@app.post("/admin/servers/replace")
def admin_replace_server():
    return redirect(url_for("admin"))


@app.post("/admin/servers/<int:server_id>/delete")
def admin_delete_server(server_id):
    return redirect(url_for("admin"))


@app.post("/admin/servers/<int:server_id>/restart-xray")
def admin_restart_xray(server_id):
    return redirect(url_for("admin"))


@app.post("/admin/servers/<int:server_id>/auto-restart-xray")
def admin_toggle_xray_auto_restart(server_id):
    return redirect(url_for("admin"))


@app.post("/admin/settings")
def admin_settings():
    return redirect(url_for("admin"))


@app.post("/admin/servers/backup")
def admin_backup_servers():
    return redirect(url_for("admin"))


@app.post("/admin/broadcast")
def admin_broadcast():
    return redirect(url_for("admin"))


@app.post("/admin/stats")
def admin_stats():
    return redirect(url_for("admin"))


@app.post("/admin/bot-status")
def admin_bot_status():
    return redirect(url_for("admin"))


@app.post("/admin/self-balance")
def admin_self_balance():
    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5051, debug=False)
