/**
 * ITAD 가격 데이터 프록시 (Cloudflare Worker).
 *
 * 브라우저(GitHub Pages)가 직접 ITAD 를 부르면 API 키가 노출된다.
 * 이 Worker 가 키를 secret 으로 숨긴 채 중계하고, 엣지 캐시로 ITAD rate limit 을 보호한다.
 *
 *   GET /deals?country=KR&shops=steam,epic&max=1500
 *     -> { generated_at, country, count, deals: [{title, shop, cut, price, regular, low, currency, url, thumb}] }
 *
 * 배포: worker/ 에서  `npx wrangler deploy`
 * 키 등록: `npx wrangler secret put ITAD_API_KEY`
 */

const ITAD = "https://api.isthereanydeal.com";
const CACHE_TTL = 1800; // 엣지 캐시 30분 — 방문자가 많아도 ITAD 는 30분당 1회만 조회
const PAGE = 200; // ITAD deals/v2 페이지 최대 크기
const HARD_MAX = 3000;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return cors(new Response(null, { status: 204 }));
    if (url.pathname === "/deals") return handleDeals(request, url, env, ctx);
    return cors(new Response("ITAD proxy. Use /deals", { status: 200 }));
  },
};

async function handleDeals(request, url, env, ctx) {
  if (!env.ITAD_API_KEY) return json({ error: "ITAD_API_KEY 미설정" }, 500);

  const cache = caches.default;
  const cacheKey = new Request(url.toString(), { method: "GET" });
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  const country = (url.searchParams.get("country") || "KR").toUpperCase();
  const max = Math.min(parseInt(url.searchParams.get("max") || "1500", 10) || 1500, HARD_MAX);
  const shopsParam = (url.searchParams.get("shops") || "").toLowerCase().trim();
  const shops = shopsParam ? new Set(shopsParam.split(",").map((s) => s.trim())) : null;

  const rows = [];
  let offset = 0;
  while (rows.length < max) {
    const limit = Math.min(PAGE, max - rows.length);
    const api =
      `${ITAD}/deals/v2?key=${env.ITAD_API_KEY}` +
      `&country=${country}&sort=rank&limit=${limit}&offset=${offset}`;
    const r = await fetch(api);
    if (!r.ok) return json({ error: `ITAD ${r.status}` }, 502);
    const data = await r.json();
    const list = data.list || [];
    if (!list.length) break;
    for (const it of list) {
      const d = it.deal;
      const cut = (d && d.cut) || 0;
      if (cut <= 0) continue;
      const shopName = (d.shop && d.shop.name) || "";
      if (shops && !shops.has(shopName.toLowerCase())) continue;
      rows.push({
        title: it.title,
        shop: shopName,
        cut,
        price: (d.price && d.price.amount) ?? 0,
        regular: (d.regular && d.regular.amount) ?? 0,
        low: (d.historyLow && d.historyLow.all && d.historyLow.all.amount) ?? null,
        currency: (d.price && d.price.currency) || "",
        url: d.url || "",
        thumb: (it.assets && it.assets.boxart) || "",
      });
      if (rows.length >= max) break;
    }
    if (!data.hasMore) break;
    offset = data.nextOffset ?? offset + list.length;
  }

  const resp = json({
    generated_at: new Date().toISOString(),
    country,
    count: rows.length,
    deals: rows,
  });
  resp.headers.set("Cache-Control", `public, max-age=${CACHE_TTL}`);
  ctx.waitUntil(cache.put(cacheKey, resp.clone()));
  return resp;
}

function json(obj, status = 200) {
  return cors(
    new Response(JSON.stringify(obj), {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    }),
  );
}

function cors(resp) {
  resp.headers.set("Access-Control-Allow-Origin", "*");
  resp.headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
  return resp;
}
