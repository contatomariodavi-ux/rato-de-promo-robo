"""Leitura das ofertas e cupons do Promobit.

O Promobit é uma comunidade onde a galera posta e vota promoção. As páginas
trazem os dados estruturados (preço, cupom, loja, votos e o histórico de
preço do produto), então o robô lê esses dados direto, sem adivinhar HTML.
"""
from __future__ import annotations

import json
import re
import time

import requests

BASE = "https://www.promobit.com.br"
UA = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36"
)
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_URL = re.compile(r"https?://[^\s\"'<>]{8,600}")
_IGNORAR_URL = ("promobit.com.br", "linksynergy.com", "google", "facebook", "doubleclick", "schema.org")


class Promobit:
    def __init__(self, pausa: float = 1.0, timeout: int = 20):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
        self.pausa = pausa
        self.timeout = timeout

    # ------------------------------------------------------------ base
    def _get(self, url: str, **kw) -> requests.Response | None:
        time.sleep(self.pausa)
        try:
            return self.s.get(url, timeout=self.timeout, **kw)
        except requests.RequestException as e:
            print(f"  ! erro de rede em {url}: {e}")
            return None

    def _page_props(self, url: str) -> tuple[int, dict | None]:
        r = self._get(url)
        if r is None:
            return 0, None
        if r.status_code != 200:
            return r.status_code, None
        m = _NEXT.search(r.text)
        if not m:
            return r.status_code, None
        try:
            return 200, json.loads(m.group(1))["props"]["pageProps"]
        except (ValueError, KeyError):
            return 200, None

    @staticmethod
    def _achar_lista(obj, campo: str) -> list[dict]:
        if isinstance(obj, dict):
            for v in obj.values():
                if isinstance(v, list) and v and isinstance(v[0], dict) and campo in v[0]:
                    return v
                achou = Promobit._achar_lista(v, campo)
                if achou:
                    return achou
        elif isinstance(obj, list):
            for v in obj:
                achou = Promobit._achar_lista(v, campo)
                if achou:
                    return achou
        return []

    # ------------------------------------------------------------ ofertas
    def ofertas(self, subcategoria: str) -> list[dict]:
        _, pp = self._page_props(f"{BASE}/promocoes/{subcategoria}/s/")
        if not pp or "subcategory" not in pp:
            print(f"  ! subcategoria '{subcategoria}' não encontrada no Promobit")
            return []
        return self._achar_lista(pp.get("serverOffers"), "offerPrice")

    def detalhes(self, slug: str) -> tuple[int, dict | None]:
        """Página da oferta. Retorna (status_http, serverOffer)."""
        status, pp = self._page_props(f"{BASE}/oferta/{slug}/")
        if not pp:
            return status, None
        return status, pp.get("serverOffer")

    def link_da_loja(self, oferta_id: int, dominio: str) -> str | None:
        """Link de saída pra loja (com a tag do Promobit, que a gente troca pela nossa)."""
        r = self._get(f"{BASE}/Redirect/to/{oferta_id}/")
        if r is None or r.status_code != 200:
            return None
        links = [u for u in _URL.findall(r.text) if not any(x in u for x in _IGNORAR_URL)]
        raiz = dominio.split(".")[0] if dominio else ""
        for u in links:
            if raiz and raiz in u:
                return u
        return links[0] if links else None

    def link_curto_resolvido(self, url: str) -> str:
        """Segue um redirecionamento (amzn.to, meli.la...) sem abrir a página final."""
        try:
            time.sleep(self.pausa)
            r = self.s.head(url, allow_redirects=False, timeout=self.timeout)
            return r.headers.get("Location") or url
        except requests.RequestException:
            return url

    # ------------------------------------------------------------ cupons
    def cupons(self, loja_param: str) -> list[dict]:
        cache = self.__dict__.setdefault("_cache_cupons", {})
        if loja_param not in cache:
            cache[loja_param] = self._cupons(loja_param)
        return cache[loja_param]

    def _cupons(self, loja_param: str) -> list[dict]:
        _, pp = self._page_props(f"{BASE}/cupons/loja/{loja_param}/")
        if not pp:
            return []
        sc = pp.get("serverCoupons")
        if isinstance(sc, dict):
            sc = sc.get("coupons")  # "couponsRelated" são de outras lojas
        if isinstance(sc, list) and sc and isinstance(sc[0], dict):
            return sc
        return self._achar_lista(pp, "couponCode")


def foto(oferta: dict, tamanho: int = 268) -> str | None:
    caminho = oferta.get("offerPhoto")
    if not caminho:
        return None
    if caminho.startswith("http"):
        return caminho
    return f"https://i.promobit.com.br/{tamanho}{caminho}"
