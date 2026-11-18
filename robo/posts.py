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


# ---- voz do Rato -------------------------------------------------------
ABERTURAS = [
    "Farejei essa e corri pra cá!",
    "Olha o que eu achei escondido {na_loja}!",
    "Roí o preço dessa até o osso!",
    "Essa aqui o Rato não deixa passar!",
    "Saí do buraco só pra te mostrar essa!",
    "Cheiro de oferta boa no ar!",
]
DESTAQUES = {
    "Menor preço já registrado": "Menor preço que eu já farejei",
    "Pertinho do menor preço já registrado": "Quase no menor preço que eu já vi",
    "Uma das doses mais baratas do mercado": "Dose baratinha, do jeito que rato gosta",
}


def _na(loja: str) -> str:
    """'na Amazon', 'no Mercado Livre', 'na Shopee'."""
    return ("no " if loja.lower().startswith("mercado") else "na ") + loja


def _sorteio(chave: str, opcoes: list[str]) -> str:
    """Escolhe uma frase pelo título, pra variar entre posts sem mudar o mesmo post."""
    return opcoes[sum(map(ord, chave)) % len(opcoes)]


def _wa_para_html(texto: str) -> str:
    """Converte a marcação do WhatsApp (*negrito*, ~riscado~, _itálico_) pro HTML do Telegram."""
    t = html.escape(texto)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w~])~([^~\n]+)~(?![\w~])", r"<s>\1</s>", t)
    t = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<i>\1</i>", t)
    return t


def montar_oferta(dados: dict) -> dict:
    """dados: titulo, preco, antigo, preco_dose, cupom, destaque, loja, link"""
    titulo = _titulo_curto(dados["titulo"])
    preco = dados["preco"]
    antigo = dados.get("antigo")
    link = dados.get("link") or PLACEHOLDER
    abertura = _sorteio(titulo, ABERTURAS).format(na_loja=_na(dados["loja"]))

    wa = [f"🐀 *{abertura}*", "", f"*{titulo}*"]
    wa.append(f"~{brl(antigo)}~ por *{brl(preco)}*" if antigo else f"Por *{brl(preco)}*")
    if dados.get("preco_dose"):
        wa.append(f"💪 {brl(dados['preco_dose'])} a dose")
    if dados.get("destaque"):
        wa.append(f"📉 {DESTAQUES.get(dados['destaque'], dados['destaque'])}")
    cupom = _linha_cupom(dados.get("cupom"))
    if cupom:
        rot, val = cupom
        wa.append(f"🏷️ Usa o cupom *{val}* no carrinho" if rot else f"🏷️ {val}")
    wa += ["", f"🛒 {dados['loja']}", f"👉 {link}"]
    if dados.get("anuncio"):
        wa.append("_Anúncio_")
    texto = "\n".join(wa)
    return {"whatsapp": texto, "telegram": _wa_para_html(texto)}


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
    desconto = " ".join(str(dados["desconto"]).split())
    titulo = re.sub(r"^cupom\s+[^:]{0,40}:\s*", "", titulo, flags=re.I)
    if desconto and titulo.lower().startswith(desconto.lower()):
        linha = f"*{titulo[:len(desconto)]}*{titulo[len(desconto):]}"
    else:
        linha = f"*{desconto}*: {titulo}"
    wa = [f"🐀 *Achei cupom {_na(dados['loja'])}!*", "", linha, f"🏷️ Código: *{dados['codigo']}*"]
    if validade:
        wa.append(f"⏰ Vale até {validade}")
    wa += ["", f"👉 {link}"]
    texto = "\n".join(wa)
    return {"whatsapp": texto, "telegram": _wa_para_html(texto)}


def montar_esgotado(titulo: str, cupom: str | None) -> dict:
    titulo = _titulo_curto(titulo)
    if cupom and len(cupom.split()) == 1:
        topo = "❌ *CUPOM ESGOTADO!*"
        corpo = f"O cupom *{cupom}* já era. Quem pegou, pegou! Fica de olho que o Rato volta com mais 🐀"
    else:
        topo = "❌ *OFERTA ESGOTADA!*"
        corpo = "Acabou o estoque ou o preço voltou. Quem pegou, pegou! Fica de olho que o Rato volta com mais 🐀"
    texto = f"{topo}\n\n{titulo}\n{corpo}"
    return {"whatsapp": texto, "telegram": _wa_para_html(texto)}


_PRODUTO = {
    "creatina": ("Creatina", "a", "💪"),
    "whey": ("Whey", "o", "🥤"),
}


def montar_termometro(linhas: dict, cfg: dict) -> dict:
    """linhas: {tipo: {dose, titulo, preco, loja}} com o menor preço por dose do dia."""
    blocos, status = [], []
    for tipo, r in linhas.items():
        nome, g, emoji = _PRODUTO[tipo]
        teto = float(cfg["preco_max_por_dose"][tipo])
        dose = float(r["dose"])
        if tipo == "creatina":
            extra = f" ({brl(dose * 1000 / cfg['dose_gramas'][tipo])} o quilo)"
        else:
            extra = f" ({brl(dose * 900 / cfg['dose_gramas'][tipo])} o pote de 900g)"
        if dose <= teto * 0.85:
            status.append("verde")
            cab = f"🟢 *Tá barat{g}, pode comprar!*"
            fim = None
        elif dose <= teto:
            status.append("amarelo")
            cab = "🟡 *Preço ok*, compra se tiver precisando"
            fim = None
        else:
            status.append("vermelho")
            cab = f"🔴 *Tá car{g}, não compra agora!*"
            fim = f"Bom mesmo é até {brl(teto)} a dose."
        bloco = [f"{emoji} *{nome}*: {cab}",
                 f"O melhor preço que eu achei foi {brl(dose)} a dose{extra}."]
        if fim:
            bloco.append(fim)
        blocos.append("\n".join(bloco))

    if all(s == "vermelho" for s in status):
        topo = "🐀 *Galera, segura a carteira!*"
        rodape = "Quando baixar eu aviso aqui. Rato esperto não paga caro 🐀"
    elif all(s == "verde" for s in status):
        topo = "🐀 *Hora de encher o pote!*"
        rodape = "As melhores ofertas eu posto aqui ao longo do dia 🐀"
    elif "vermelho" in status:
        topo = "🐀 *Termômetro do Rato*"
        rodape = "O que tá caro eu aviso aqui quando baixar. Rato esperto não paga caro 🐀"
    else:
        topo = "🐀 *Termômetro do Rato*"
        rodape = "As melhores ofertas eu posto aqui ao longo do dia 🐀"
    texto = "\n\n".join([topo] + blocos + [rodape])
    return {"whatsapp": texto, "telegram": _wa_para_html(texto)}


def link_whatsapp(texto: str, limite: int = 2000) -> str:
    """Link que abre o WhatsApp com o texto já preenchido."""
    url = "https://wa.me/?text=" + quote(texto, safe="")
    if len(url) <= limite:
        return url
    curto = texto.replace(f"\n\n_{RODAPE}_", "")
    return "https://wa.me/?text=" + quote(curto, safe="")[: limite - 20]
