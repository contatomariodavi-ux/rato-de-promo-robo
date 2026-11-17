"""Textos dos posts: versão WhatsApp (*negrito*, ~riscado~) e versão Telegram (HTML)."""
from __future__ import annotations

import html
import re
from datetime import datetime
from urllib.parse import quote

PLACEHOLDER = "COLE_SEU_LINK_AQUI"
RODAPE = "Preço e estoque podem mudar a qualquer momento."


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _titulo_curto(t: str, n: int = 90) -> str:
    t = " ".join((t or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _linha_cupom(cupom: str | None) -> tuple[str, str] | None:
    """(rótulo, valor). Cupom de uma palavra vira código em negrito; frase vira instrução."""
    if not cupom:
        return None
    cupom = " ".join(cupom.split())
    if len(cupom.split()) == 1:
        return ("Cupom: ", cupom)
    return ("", cupom)


def montar_oferta(dados: dict) -> dict:
    """dados: titulo, preco, antigo, preco_dose, dose_g, cupom, destaque, loja, vendedor, link"""
    titulo = _titulo_curto(dados["titulo"])
    preco = dados["preco"]
    antigo = dados.get("antigo")
    link = dados.get("link") or PLACEHOLDER

    wa, tg = [], []
    wa.append(f"🔥 *{titulo}*")
    tg.append(f"🔥 <b>{html.escape(titulo)}</b>")
    wa.append("")
    tg.append("")
    if antigo:
        pct = round((1 - preco / antigo) * 100)
        wa.append(f"~{brl(antigo)}~ ➜ *{brl(preco)}* (-{pct}%)")
        tg.append(f"<s>{brl(antigo)}</s> ➜ <b>{brl(preco)}</b> (-{pct}%)")
    else:
        wa.append(f"💰 *{brl(preco)}*")
        tg.append(f"💰 <b>{brl(preco)}</b>")
    if dados.get("preco_dose"):
        d = f"💪 {brl(dados['preco_dose'])} por dose ({dados['dose_g']:g}g)"
        wa.append(d)
        tg.append(html.escape(d))
    cupom = _linha_cupom(dados.get("cupom"))
    if cupom:
        rot, val = cupom
        if rot:
            wa.append(f"🏷️ {rot}*{val}*")
            tg.append(f"🏷️ {rot}<code>{html.escape(val)}</code>")
        else:
            wa.append(f"🏷️ {val}")
            tg.append(f"🏷️ {html.escape(val)}")
    if dados.get("destaque"):
        wa.append(f"📉 {dados['destaque']}")
        tg.append(f"📉 {html.escape(dados['destaque'])}")
    loja = dados["loja"]
    if dados.get("vendedor"):
        loja += f" (vendido por {dados['vendedor']})"
    wa.append(f"🛒 {loja}")
    tg.append(f"🛒 {html.escape(loja)}")
    wa += ["", f"👉 {link}", "", f"_{RODAPE}_"]
    tg += ["", f"👉 {html.escape(link)}", "", f"<i>{RODAPE}</i>"]
    return {"whatsapp": "\n".join(wa), "telegram": "\n".join(tg)}


def ler_data(texto: str | None) -> datetime | None:
    """Lê datas do Promobit, tipo 2026-12-17T23:59:59-0300."""
    if not texto:
        return None
    t = texto.strip().replace("Z", "+00:00")
    m = re.match(r"^(.*[T ]\d{2}:\d{2}(?::\d{2})?)([+-])(\d{2}):?(\d{2})$", t)
    if m:
        t = f"{m.group(1)}{m.group(2)}{m.group(3)}:{m.group(4)}"
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        return None


def _validade(ate: str | None) -> str | None:
    d = ler_data(ate)
    return d.strftime("%d/%m às %Hh%M") if d else None


def montar_cupom(dados: dict) -> dict:
    """dados: loja, desconto, titulo, codigo, ate, link"""
    link = dados.get("link") or PLACEHOLDER
    titulo = _titulo_curto(dados["titulo"], 120)
    validade = _validade(dados.get("ate"))
    wa = [f"🎟️ *CUPOM {dados['loja'].upper()}: {dados['desconto']}*", "", titulo, "", f"Código: *{dados['codigo']}*"]
    tg = [
        f"🎟️ <b>CUPOM {html.escape(dados['loja'].upper())}: {html.escape(dados['desconto'])}</b>",
        "",
        html.escape(titulo),
        "",
        f"Código: <code>{html.escape(dados['codigo'])}</code>",
    ]
    if validade:
        wa.append(f"⏰ Válido até {validade}")
        tg.append(f"⏰ Válido até {validade}")
    wa += ["", f"👉 {link}"]
    tg += ["", f"👉 {html.escape(link)}"]
    return {"whatsapp": "\n".join(wa), "telegram": "\n".join(tg)}


def montar_esgotado(titulo: str, cupom: str | None) -> dict:
    titulo = _titulo_curto(titulo)
    if cupom and len(cupom.split()) == 1:
        topo = "❌ *CUPOM ESGOTADO*"
        corpo = f"O cupom *{cupom}* acabou. Quem pegou, pegou! Fica de olho que o Rato volta com mais 🐀"
    else:
        topo = "❌ *OFERTA ESGOTADA*"
        corpo = "Acabou o estoque ou o preço voltou. Fica de olho que o Rato volta com mais 🐀"
    wa = f"{topo}\n\n{titulo}\n{corpo}"
    tg = f"{_wa_para_html(topo)}\n\n{html.escape(titulo)}\n{_wa_para_html(corpo)}"
    return {"whatsapp": wa, "telegram": tg}


def _wa_para_html(texto: str) -> str:
    """Converte *negrito* do WhatsApp pra <b>negrito</b> do Telegram."""
    return re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", html.escape(texto))


def link_whatsapp(texto: str, limite: int = 2000) -> str:
    """Link que abre o WhatsApp com o texto já preenchido."""
    url = "https://wa.me/?text=" + quote(texto, safe="")
    if len(url) <= limite:
        return url
    curto = texto.replace(f"\n\n_{RODAPE}_", "")
    return "https://wa.me/?text=" + quote(curto, safe="")[: limite - 20]
