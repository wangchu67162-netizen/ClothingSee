#!/usr/bin/env python
"""Independent acceptance check for 衣见 ATELIER.

Run against a live backend (default http://127.0.0.1:8000), using the demo
account. It exercises auth, catalog, cart, platform checkout, small-model APIs,
the five-agent SSE pipeline, assistant product cards, and a real Playwright
Edge checkout.

Usage:
    cd C:/Users/cc/Desktop/服装平台项目
    PYTHONIOENCODING=utf-8 backend/.venv/Scripts/python.exe scripts/acceptance_check.py

Note: this creates orders and agent sessions for the demo account. For a clean
demo database, stop the backend, delete backend/data/app.db, restart (seeds).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("YIJIAN_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SAMPLE = ROOT / "backend/app/static/images/samples/outfit-demo.webp"
OUT = ROOT / "backend/runtime/acceptance"
OUT.mkdir(parents=True, exist_ok=True)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), "|", name, "|", detail)


def sse(client: httpx.Client, path: str, **kwargs):
    event = "message"
    data_lines: list[str] = []
    with client.stream("POST", path, **kwargs) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line == "":
                if event != "message" or data_lines:
                    raw = "\n".join(data_lines)
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = raw
                    yield event, payload
                event = "message"
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=httpx.Timeout(280.0, connect=15.0)) as client:
        health = client.get("/api/health")
        check("backend health", health.status_code == 200, str(health.status_code))
        meta = client.get("/api/meta").json()
        check("mock mode (no key)", meta.get("mode") == "mock", json.dumps(meta, ensure_ascii=False))
        root = client.get("/")
        check(
            "built frontend served",
            root.status_code == 200 and "text/html" in root.headers.get("content-type", ""),
            root.headers.get("content-type", ""),
        )

        login = client.post("/api/auth/login", json={"username": "demo", "password": "demo123"})
        check("demo login", login.status_code == 200, str(login.status_code))
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        me = client.get("/api/auth/me", headers=headers)
        check("auth me", me.status_code == 200 and me.json().get("username") == "demo", me.text[:120])

        products = client.get("/api/products", params={"q": "风衣", "page_size": 5}, headers=headers).json()
        check("search 风衣", products.get("total", 0) >= 1, f"total={products.get('total')}")
        product = products["items"][0]
        product_id = product["id"]
        detail = client.get(f"/api/products/{product_id}", headers=headers)
        check("product detail", detail.status_code == 200 and bool(detail.json()["name"]), detail.json().get("name", ""))

        client.delete("/api/cart", headers=headers)
        add = client.post(
            "/api/cart",
            headers=headers,
            json={"product_id": product_id, "quantity": 1, "size": product["sizes"][0], "color": product["colors"][0]},
        )
        check("cart add", add.status_code == 200 and add.json()["total_quantity"] >= 1, add.text[:160])
        order = client.post(
            "/api/orders",
            headers=headers,
            json={
                "shipping": {
                    "name": "验收用户",
                    "phone": "13800000000",
                    "address": "上海市徐汇区云裳路 88 号",
                },
                "note": "独立验收",
            },
        )
        check(
            "platform checkout",
            order.status_code == 200 and order.json().get("source") == "platform",
            order.text[:160],
        )
        platform_order_no = order.json().get("order_no") if order.status_code == 200 else ""

        status = client.get("/api/small-models/status")
        check("small models status", status.status_code == 200, status.text[:180])
        cheb = client.post("/api/small-models/kg/chebyshev", json={"a": [1, 5], "b": [3, 2]})
        check(
            "chebyshev = 3.0",
            cheb.status_code == 200 and abs(float(cheb.json().get("distance", -1)) - 3.0) < 1e-9,
            cheb.text[:120],
        )
        with SAMPLE.open("rb") as handle:
            embed = client.post(
                "/api/small-models/vision/embed",
                files={"file": ("outfit-demo.webp", handle, "image/webp")},
            )
        check("vision embed dim 256", embed.status_code == 200 and embed.json().get("dim") == 256, embed.text[:160])
        with SAMPLE.open("rb") as handle:
            similar = client.post(
                "/api/small-models/vision/similar",
                files={"file": ("outfit-demo.webp", handle, "image/webp")},
                data={"top_k": "4"},
            )
        sim_body = similar.json() if similar.status_code == 200 else {}
        check(
            "vision similar top-k (multipart)",
            similar.status_code == 200 and 1 <= len(sim_body.get("matches", [])) <= 4,
            similar.text[:200],
        )

        with SAMPLE.open("rb") as handle:
            events = list(
                sse(
                    client,
                    "/api/recommend/image",
                    headers=headers,
                    files={"file": ("outfit-demo.webp", handle, "image/webp")},
                    data={"budget": "1500", "note": "通勤，想要显高"},
                )
            )
        names = [name for name, _ in events]
        agent_messages = [data for name, data in events if name == "agent_message"]
        revisions = [data for name, data in events if name == "revision"]
        finals = [data for name, data in events if name == "final"]
        agents = {m.get("agent") for m in agent_messages if isinstance(m, dict)}
        rounds = {m.get("round") for m in agent_messages if isinstance(m, dict)}
        check("recommend SSE completes", "done" in names, ",".join(sorted(set(names)))[:300])
        check(
            "five agents spoke",
            agents >= {"fashion", "art", "aesthetics", "price", "comfort"},
            str(sorted(agents)),
        )
        check("two discussion rounds", rounds >= {1, 2}, str(sorted(rounds)))
        check("revisions from peer discussion", len(revisions) > 0, f"revisions={len(revisions)}")
        check(
            "final top3 + outfit",
            bool(finals)
            and len(finals[-1].get("recommendations", [])) >= 1
            and len(finals[-1].get("outfit", [])) >= 1,
            f"recs={len(finals[-1].get('recommendations', [])) if finals else 0}",
        )
        (OUT / "recommend_events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

        assistant_events = list(
            sse(
                client,
                "/api/assistant/chat",
                headers=headers,
                json={"message": "我想买一件适合秋天的风衣"},
            )
        )
        assistant_names = [name for name, _ in assistant_events]
        cards = next((data for name, data in assistant_events if name == "products"), {})
        check(
            "assistant recommend SSE",
            "products" in assistant_names and len(cards.get("items", [])) >= 1,
            ",".join(sorted(set(assistant_names)))[:240],
        )
        (OUT / "assistant_recommend_events.json").write_text(
            json.dumps(assistant_events, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        order_events = list(
            sse(
                client,
                "/api/assistant/chat",
                headers=headers,
                json={"message": "帮我下单暮色长风衣，M 码"},
            )
        )
        order_names = [name for name, _ in order_events]
        steps = [data for name, data in order_events if name == "browse_step"]
        created = next((data for name, data in order_events if name == "order_created"), {})
        errors = [data for name, data in order_events if name in {"error", "warning"}]
        check(
            "assistant order SSE completes",
            "done" in order_names or "order_created" in order_names,
            ",".join(sorted(set(order_names)))[:300],
        )
        check("browser steps emitted", len(steps) >= 4, f"steps={len(steps)}")
        screenshots = [s.get("screenshot") for s in steps if isinstance(s, dict) and s.get("screenshot")]
        check("browser screenshots emitted", len(screenshots) >= 3, f"screenshots={len(screenshots)}")
        if screenshots:
            shot_status = client.get(screenshots[-1])
            check("screenshot URL serves", shot_status.status_code == 200, screenshots[-1])
        check("agent order created", bool(created.get("order_no")), json.dumps(created, ensure_ascii=False)[:240])
        if errors:
            print("assistant order warnings/errors:", json.dumps(errors, ensure_ascii=False)[:1200])
        (OUT / "assistant_order_events.json").write_text(
            json.dumps(order_events, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        orders = client.get("/api/orders", headers=headers).json()
        agent_orders = [o for o in orders if o.get("source") == "agent"]
        match = next((o for o in agent_orders if o.get("order_no") == created.get("order_no")), None)
        check("agent order persisted", match is not None, f"agent_orders={len(agent_orders)}")
        if match:
            check("agent order has session", bool(match.get("agent_session_id")), match.get("agent_session_id", ""))
        check(
            "platform order persisted",
            any(o.get("order_no") == platform_order_no for o in orders),
            platform_order_no,
        )

        page = client.get("/api/recommend/history", headers=headers)
        check("stylist history", page.status_code == 200, str(page.status_code))

    failed = [{"name": name, "detail": detail} for name, ok, detail in results if not ok]
    summary = {
        "base_url": BASE,
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": failed,
        "results": [{"name": name, "passed": ok, "detail": detail} for name, ok, detail in results],
    }
    (OUT / "acceptance-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nSUMMARY", summary["passed"], "/", summary["total"], "passed")
    if failed:
        print("FAILED:", json.dumps(failed, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
