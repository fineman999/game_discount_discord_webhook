# deal-proxy (Cloudflare Worker)

GitHub Pages 의 정적 페이지가 ITAD API 키를 노출하지 않고 가격 데이터를 받도록 중계하는 프록시.

## 동작

```
브라우저(docs/index.html) ──fetch──▶ Worker ──key 숨김──▶ ITAD
                                       └ 엣지 캐시 30분 (rate limit 보호)
```

- `GET /deals?country=KR&shops=steam,epic&max=1500`
- 응답: `{ generated_at, country, count, deals: [{title, shop, cut, price, regular, low, currency, url, thumb}] }`
- CORS `*` 허용 → 어떤 페이지에서도 fetch 가능.

## 배포 (무료)

1. [Cloudflare 계정](https://dash.cloudflare.com/sign-up) 생성 (무료).
2. 이 디렉터리에서:
   ```bash
   npx wrangler login                    # 브라우저 인증
   npx wrangler secret put ITAD_API_KEY  # ITAD 키 입력 (깃/코드에 안 남음)
   npx wrangler deploy
   ```
3. 출력된 URL(`https://deal-proxy.<subdomain>.workers.dev`)을 복사.
4. `../docs/index.html` 상단의 `API_BASE` 상수에 그 URL 을 넣는다.

## 비용

Cloudflare Workers 무료 티어 = 하루 10만 요청. 엣지 캐시 30분이라 ITAD 실제 호출은 하루 수십 번 수준.
