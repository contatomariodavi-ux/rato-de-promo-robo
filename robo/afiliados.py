"""Troca o link da oferta pelo link de afiliado do Rato de Promo.

- Amazon: automático (tag de associado no link limpo do produto).
- Shopee: automático se a API de afiliados estiver liberada (APP ID + SECRET).
- Mercado Livre: o ML não tem API de link de afiliado, então o robô te manda
  o botão pra abrir o produto e você gera o link no app (Compartilhar).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import quote_plus

import requests

_ASIN = re.compile(r"/(?:dp|gp/product|gp/aw/d|product)/([A-Z0-9]{10})(?:[/?]|$)")
SHOPEE_API = "https://open-api.affiliate.shopee.com.br/graphql"


@dataclass
class Link:
    url: str | None          # link de afiliado pronto (None = precisa gerar na mão)
    abrir: str | None = None  # link pra você abrir o produto e gerar o seu
    manual: bool = False


def link_amazon(url: str, tag: str | None) -> Link:
    m = _ASIN.search(url or "")
    if not m:
        return Link(None, url, manual=True)
    limpo = f"https://www.amazon.com.br/dp/{m.group(1)}"
    if not tag:
        return Link(None, limpo, manual=True)
    return Link(f"{limpo}?tag={tag}")


def link_shopee(url: str, app_id: str | None, secret: str | None) -> Link:
    if not (app_id and secret and url):
        return Link(None, url, manual=True)
    url_seguro = url.replace("\\", "").replace('"', "")
    consulta = (
        'mutation{generateShortLink(input:{originUrl:"%s",subIds:["ratodepromo"]}){shortLink}}'
        % url_seguro
    )
    corpo = json.dumps({"query": consulta}, separators=(",", ":"))
    ts = str(int(time.time()))
    assinatura = hashlib.sha256(f"{app_id}{ts}{corpo}{secret}".encode()).hexdigest()
    cab = {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={ts}, Signature={assinatura}",
    }
    try:
        r = requests.post(SHOPEE_API, data=corpo, headers=cab, timeout=20)
        dados = r.json()
        curto = (((dados or {}).get("data") or {}).get("generateShortLink") or {}).get("shortLink")
        if curto:
            return Link(curto)
        print(f"  ! Shopee não gerou link: {str(dados)[:200]}")
    except (requests.RequestException, ValueError) as e:
        print(f"  ! erro na API da Shopee: {e}")
    return Link(None, url, manual=True)


def link_mercado_livre(url_oferta: str | None, titulo: str) -> Link:
    busca = "https://lista.mercadolivre.com.br/" + quote_plus(titulo[:60]).replace("+", "-")
    return Link(None, url_oferta or busca, manual=True)


def gerar(loja: str, url_saida: str | None, titulo: str, segredos: dict) -> Link:
    if loja == "amazon":
        return link_amazon(url_saida or "", segredos.get("AMAZON_TAG"))
    if loja == "shopee":
        return link_shopee(url_saida or "", segredos.get("SHOPEE_APP_ID"), segredos.get("SHOPEE_SECRET"))
    if loja == "mercado-livre":
        return link_mercado_livre(url_saida, titulo)
    return Link(None, url_saida, manual=True)
