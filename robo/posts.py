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


_MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "em", "com", "para", "sem", "x", "a", "o"}


def _gramas_em_kg(m: re.Match) -> str:
    g = int(m.group(1))
    if g >= 1000 and g % 100 == 0:
        kg = f"{g / 1000:g}".replace(".", ",")
        return f"{kg}kg"
    return m.group(0)


def _titulo_curto(t: str, n: int = 70) -> str:
    """Arruma o título: Maiúsculas, 1200g vira 1,2kg, corta no tamanho."""
    t = " ".join((t or "").split())
    if t and not any(c.isupper() for c in t[1:]):  # veio tudo minúsculo
        palavras = []
        for i, p in enumerate(t.split()):
            if any(ch.isdigit() for ch in p) or (i > 0 and p.lower() in _MINUSCULAS):
                palavras.append(p.lower())
            else:
                palavras.append(p[:1].upper() + p[1:])
        t = " ".join(palavras)
    t = re.sub(r"\b(\d{4,5})\s?g\b", _gramas_em_kg, t, flags=re.I)
    if len(t) <= n:
        return t
    return t[:n].rsplit(" ", 1)[0].rstrip(" -–,") + "…"


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

    wa, tg = [f"🔥 *{titulo}*", ""], [f"🔥 <b>{html.escape(titulo)}</b>", ""]
    if antigo:
        wa.append(f"~{brl(antigo)}~ por *{brl(preco)}*")
        tg.append(f"<s>{brl(antigo)}</s> por <b>{brl(preco)}</b>")
    else:
        wa.append(f"Por *{brl(preco)}*")
        tg.append(f"Por <b>{brl(preco)}</b>")
    if dados.get("preco_dose"):
        wa.append(f"💪 {brl(dados['preco_dose'])} a dose")
        tg.append(f"💪 {brl(dados['preco_dose'])} a dose")
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
    wa += ["", f"🛒 {dados['loja']}", f"👉 {link}"]
    tg += ["", f"🛒 {html.escape(dados['loja'])}", f"👉 {html.escape(link)}"]
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
