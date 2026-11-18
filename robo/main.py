"""Rodada do robô do Rato de Promo.

1. Responde /start e /id no Telegram (pra você descobrir os IDs).
2. Confere se algum post esgotou e avisa ("cupom esgotado").
3. No horário de postar: caça ofertas e cupons, filtra, escolhe as melhores
   respeitando o mix (70% suplementos / 30% fitness) e posta.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import afiliados, analise, posts
from .promobit import Promobit, foto
from .telegram import Telegram

RAIZ = Path(__file__).resolve().parent.parent
ARQ_ESTADO = RAIZ / "dados" / "estado.json"
TZ = ZoneInfo("America/Sao_Paulo")
FIM = ("EXPIR", "FINISH", "ENCERR", "ESGOT", "CLOSE", "ENDED", "SOLD", "INACTIV", "REJECT", "DELET", "UNAVAIL", "OUT_OF")
ATIVOS = {"RECENTS", "APPROVED", "TOP_OFFER", "HIGHLIGHT", "FEATURED"}


# ------------------------------------------------------------------ estado
def carregar_estado() -> dict:
    base = {"postados": {}, "cupons": {}, "produtos": {}, "dias": {}, "telegram_offset": 0}
    if ARQ_ESTADO.exists():
        base.update(json.loads(ARQ_ESTADO.read_text(encoding="utf-8")))
    return base


def salvar_estado(estado: dict) -> None:
    ARQ_ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ARQ_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")


def contagem_do_dia(estado: dict, hoje: str) -> dict:
    return estado["dias"].setdefault(hoje, {"total": 0, "suplementos": 0, "fitness": 0, "shopee": 0, "cupons": 0})


def limpar(estado: dict, agora: datetime, cfg: dict) -> None:
    def velho(iso: str, dias: int) -> bool:
        d = posts.ler_data(iso)
        return d is None or agora - d > timedelta(days=dias)

    estado["postados"] = {k: v for k, v in estado["postados"].items() if not velho(v["quando"], 15)}
    estado["cupons"] = {k: v for k, v in estado["cupons"].items() if not velho(v["quando"], 30)}
    dias_prod = cfg["repetir_produto_depois_de_dias"] * 2
    estado["produtos"] = {k: v for k, v in estado["produtos"].items() if not velho(v["quando"], dias_prod)}
    corte = (agora - timedelta(days=7)).date().isoformat()
    estado["dias"] = {k: v for k, v in estado["dias"].items() if k >= corte}
    corte_t = (agora - timedelta(days=40)).date().isoformat()
    estado["termometro"] = {k: v for k, v in (estado.get("termometro") or {}).items() if k >= corte_t}


# ------------------------------------------------------------------ telegram: comandos
def responder_comandos(tg: Telegram, estado: dict) -> None:
    for upd in tg.novidades(estado["telegram_offset"] + 1):
        estado["telegram_offset"] = max(estado["telegram_offset"], upd["update_id"])
        msg = upd.get("message") or upd.get("channel_post") or {}
        texto = (msg.get("text") or "").strip().lower()
        chat = msg.get("chat") or {}
        if texto.startswith(("/start", "/id")) and chat.get("id"):
            tipo = "grupo/canal" if chat.get("type") != "private" else "conversa"
            tg.mensagem(
                chat["id"],
                f"🐀 ID deste(a) {tipo}: <code>{chat['id']}</code>\n\n"
                "Copia esse número e cola no GitHub, em Settings › Secrets and variables › Actions.",
            )
            print(f"Respondi /id no chat {chat['id']} ({tipo})")


# ------------------------------------------------------------------ esgotados
def oferta_acabou(status_http: int, oferta: dict | None) -> bool:
    if status_http in (404, 410):
        return True
    if not oferta:
        return False
    nome = (oferta.get("offerStatusName") or "").upper()
    if nome and nome not in ATIVOS and not any(k in nome for k in FIM):
        print(f"  ? status novo no Promobit: {nome} (não marquei como esgotado)")
    return any(k in nome for k in FIM)


def avisar_esgotado(item: dict, tg: Telegram, admin, grupo_tg) -> None:
    textos = posts.montar_esgotado(item["titulo"], item.get("cupom"))
    if grupo_tg and item.get("msg_grupo"):
        tg.editar(grupo_tg, item["msg_grupo"], "❌ <b>ESGOTADO</b>\n\n" + item["texto_tg"], item.get("foto", False))
        tg.mensagem(grupo_tg, textos["telegram"], responder_a=item["msg_grupo"])
    if admin:
        tg.mensagem(
            admin,
            textos["telegram"],
            Telegram.botoes([("Mandar no WhatsApp", posts.link_whatsapp(textos["whatsapp"]))]),
            previa=False,
        )
    item["esgotado"] = True
    print(f"  ❌ esgotou: {item['titulo'][:70]}")


def conferir_esgotados(pb: Promobit, tg: Telegram, estado: dict, cfg: dict, agora: datetime, admin, grupo_tg) -> None:
    limite = timedelta(hours=cfg["acompanhar_esgotado_horas"])
    print("Conferindo esgotados…")

    ofertas = [
        v for v in estado["postados"].values()
        if not v.get("esgotado") and agora - posts.ler_data(v["quando"]) <= limite
    ]
    ofertas.sort(key=lambda v: v.get("checado", ""))
    for item in ofertas[:25]:
        status, det = pb.detalhes(item["slug"])
        item["checado"] = agora.isoformat()
        if oferta_acabou(status, det):
            avisar_esgotado(item, tg, admin, grupo_tg)

    cupons = [
        v for v in estado["cupons"].values()
        if not v.get("esgotado") and agora - posts.ler_data(v["quando"]) <= limite * 4
    ]
    listas: dict[str, list] = {}
    for item in cupons:
        ate = posts.ler_data(item.get("ate"))
        acabou = ate is not None and ate < agora
        if not acabou:
            if item["loja_param"] not in listas:
                listas[item["loja_param"]] = pb.cupons(item["loja_param"])
            for c in listas[item["loja_param"]]:
                if str(c.get("couponId")) == item["id"] and c.get("couponStatusName") not in (None, "APPROVED"):
                    acabou = True
        if acabou:
            avisar_esgotado(item, tg, admin, grupo_tg)


# ------------------------------------------------------------------ ofertas
def escolher(aprovados: list, dia: dict, cfg: dict, limite: int) -> list:
    restantes = sorted(aprovados, key=lambda x: -x[0].nota)
    escolhidos: list = []
    chaves: set = set()
    for _ in range(limite):
        total = dia["total"] + len(escolhidos)
        cont = {g: dia[g] + sum(1 for e in escolhidos if e[0].grupo == g) for g in ("suplementos", "fitness")}
        shopee = dia["shopee"] + sum(1 for e in escolhidos if e[1]["storeParam"] == "shopee")
        deficit = {g: cfg["mix"][g] / 100 * (total + 1) - cont[g] for g in cont}
        pegou = None
        for g in sorted(cont, key=lambda g: -deficit[g]):
            for item in restantes:
                av, oferta, _ = item
                if av.grupo != g:
                    continue
                if oferta["storeParam"] == "shopee" and shopee >= analise.limite_por_porcentagem(cfg["shopee_max_pct"], total):
                    continue
                if analise.chave_produto(oferta["storeParam"], oferta["offerTitle"]) in chaves:
                    continue
                pegou = item
                break
            if pegou:
                break
        if not pegou:
            break
        escolhidos.append(pegou)
        restantes.remove(pegou)
        chaves.add(analise.chave_produto(pegou[1]["storeParam"], pegou[1]["offerTitle"]))
    return escolhidos


def registrar_termometro(estado: dict, oferta: dict, cfg: dict, agora: datetime) -> None:
    """Guarda o menor preço por dose de creatina e whey visto no dia (de marca confiável)."""
    tri = analise.triagem(oferta, "suplementos", cfg)
    if tri.tipo not in ("creatina", "whey") or tri.preco_dose is None:
        return
    if not tri.aprovada and not (tri.rejeitada or "").startswith("dose cara"):
        return
    dia = estado.setdefault("termometro", {}).setdefault(agora.date().isoformat(), {})
    atual = dia.get(tri.tipo)
    if atual is None or tri.preco_dose < atual["dose"]:
        dia[tri.tipo] = {"dose": round(tri.preco_dose, 4), "titulo": oferta["offerTitle"],
                         "preco": float(oferta["offerPrice"]), "loja": cfg["lojas"][oferta["storeParam"]]}


def cacar_ofertas(pb: Promobit, estado: dict, cfg: dict, agora: datetime, detalhar: bool = True) -> list:
    candidatos: dict[str, tuple] = {}
    for grupo, subcats in cfg["categorias"].items():
        for sc in subcats:
            lista = pb.ofertas(sc)
            print(f"  {sc}: {len(lista)} ofertas")
            for o in lista:
                oid = str(o.get("offerId"))
                if o.get("storeParam") not in cfg["lojas"]:
                    continue
                if any(k in (o.get("offerStatusName") or "").upper() for k in FIM):
                    continue
                pub = posts.ler_data(o.get("offerPublished"))
                if not pub:
                    continue
                if grupo == "suplementos" and agora - pub <= timedelta(hours=48):
                    registrar_termometro(estado, o, cfg, agora)
                if oid in estado["postados"] or oid in candidatos:
                    continue
                if agora - pub > timedelta(hours=cfg["ofertas_ate_horas"]):
                    continue
                tri = analise.triagem(o, grupo, cfg)
                if not tri.aprovada:
                    continue
                chave = analise.chave_produto(o["storeParam"], o["offerTitle"])
                antes = estado["produtos"].get(chave)
                if antes:
                    quando = posts.ler_data(antes["quando"])
                    recente = agora - quando < timedelta(days=cfg["repetir_produto_depois_de_dias"])
                    if recente and float(o["offerPrice"]) > antes["preco"] * 0.95:
                        continue
                candidatos[oid] = (grupo, o)

    if not detalhar:
        return []

    # abre a página só das mais promissoras (votos, destaque, desconto)
    def promessa(par):
        o = par[1]
        return (o.get("offerStatusName") == "TOP_OFFER", int(o.get("offerLikes") or 0),
                float(o.get("offerDiscontPercentage") or 0))

    por_grupo = {"suplementos": 12, "fitness": 8}
    aprovados = []
    for grupo, n in por_grupo.items():
        lista = sorted((c for c in candidatos.values() if c[0] == grupo), key=promessa, reverse=True)[:n]
        for _, o in lista:
            status, det = pb.detalhes(o["offerSlug"])
            if det is None or oferta_acabou(status, det):
                continue
            av = analise.avaliar(o, det, grupo, cfg)
            marca = "✅" if av.aprovada else "·"
            print(f"  {marca} [{grupo}] {o['offerTitle'][:60]} R$ {o['offerPrice']} "
                  f"→ {'nota %.0f' % av.nota if av.aprovada else av.rejeitada}")
            if av.aprovada:
                aprovados.append((av, o, det))
    return aprovados


def postar_oferta(item, pb: Promobit, tg: Telegram, estado: dict, cfg: dict, segredos: dict,
                  agora: datetime, admin, grupo_tg) -> None:
    av, o, det = item
    loja = o["storeParam"]
    loja_nome = cfg["lojas"][loja]
    url_saida = pb.link_da_loja(o["offerId"], o.get("storeDomain", ""))
    if url_saida and any(x in url_saida for x in ("amzn.to", "a.co/")):
        url_saida = pb.link_curto_resolvido(url_saida)
    link = afiliados.gerar(loja, url_saida, o["offerTitle"], segredos)

    vendedor = ((det or {}).get("storeMarketplace") or {}).get("storeMarketplaceName")
    textos = posts.montar_oferta({
        "titulo": o["offerTitle"],
        "preco": float(o["offerPrice"]),
        "antigo": analise.preco_antigo_confiavel(o, det),
        "preco_dose": av.preco_dose,
        "dose_g": av.dose_g,
        "cupom": o.get("offerCoupon"),
        "destaque": av.destaque,
        "loja": loja_nome,
        "vendedor": vendedor,
        "link": link.url,
    })
    imagem = foto(o)
    msg_grupo = None
    if grupo_tg and not link.manual:
        r = tg.foto(grupo_tg, imagem, textos["telegram"]) if imagem else tg.mensagem(grupo_tg, textos["telegram"])
        if r is None and imagem:  # foto falhou: manda só o texto
            imagem = None
            r = tg.mensagem(grupo_tg, textos["telegram"])
        msg_grupo = (r or {}).get("message_id")

    whats = posts.link_whatsapp(textos["whatsapp"])
    if link.manual and link.abrir:
        botoes = Telegram.botoes([(f"1. Pegar meu link no {loja_nome}", link.abrir)],
                                 [("2. Mandar no WhatsApp", whats)])
    else:
        botoes = Telegram.botoes([("Mandar no WhatsApp", whats)])
    if admin:
        r = tg.foto(admin, imagem, textos["telegram"], botoes) if imagem else None
        if r is None:
            tg.mensagem(admin, textos["telegram"], botoes, previa=False)

    estado["postados"][str(o["offerId"])] = {
        "titulo": o["offerTitle"], "slug": o["offerSlug"], "loja": loja, "grupo": av.grupo,
        "preco": float(o["offerPrice"]), "cupom": o.get("offerCoupon"), "quando": agora.isoformat(),
        "msg_grupo": msg_grupo, "foto": bool(imagem and msg_grupo), "texto_tg": textos["telegram"],
        "manual": link.manual,
    }
    estado["produtos"][analise.chave_produto(loja, o["offerTitle"])] = {
        "preco": float(o["offerPrice"]), "quando": agora.isoformat()}
    dia = contagem_do_dia(estado, agora.date().isoformat())
    dia["total"] += 1
    dia[av.grupo] += 1
    if loja == "shopee":
        dia["shopee"] += 1
    print(f"  📣 postei: {o['offerTitle'][:70]} ({loja_nome}{', link manual' if link.manual else ''})")


# ------------------------------------------------------------------ cupons
def postar_cupons(pb: Promobit, tg: Telegram, estado: dict, cfg: dict, segredos: dict,
                  agora: datetime, admin, grupo_tg) -> None:
    ccfg = cfg["cupons"]
    dia = contagem_do_dia(estado, agora.date().isoformat())
    vagas = min(ccfg["por_rodada"], ccfg["por_dia"] - dia["cupons"])
    if vagas <= 0:
        return
    candidatos = []
    for loja_param in cfg["lojas"]:
        for c in pb.cupons(loja_param):
            cid = str(c.get("couponId"))
            codigo = (c.get("couponCode") or "").strip()
            if cid in estado["cupons"] or c.get("couponStatusName") != "APPROVED":
                continue
            if not codigo or " " in codigo:
                continue
            texto = analise.normalizar(" ".join(str(c.get(k) or "") for k in
                                                ("couponTitle", "couponInstructions", "couponDiscountOn")))
            if any(analise.normalizar(x) in texto + " " + codigo.lower() for x in ccfg["ignorar"]):
                continue
            if not any(analise.normalizar(p) in texto for p in ccfg["palavras"]):
                continue
            ate = posts.ler_data(c.get("couponUntil"))
            if ate and ate < agora:
                continue
            pub = posts.ler_data(c.get("couponPublished"))
            if not pub or agora - pub > timedelta(hours=ccfg["ate_horas"]):
                continue
            candidatos.append((loja_param, c))

    def valor(c):
        achou = re.search(r"\d+(?:[.,]\d+)?", str(c.get("couponDiscountShort") or c.get("couponDiscountValue") or ""))
        return float(achou.group().replace(",", ".")) if achou else 0.0

    candidatos.sort(key=lambda x: valor(x[1]), reverse=True)
    for loja_param, c in candidatos[:vagas]:
        loja_nome = cfg["lojas"][loja_param]
        if loja_param == "amazon" and segredos.get("AMAZON_TAG"):
            link = f"https://www.amazon.com.br/?tag={segredos['AMAZON_TAG']}"
        else:
            link = (cfg.get("link_padrao") or {}).get(loja_param) or None
        textos = posts.montar_cupom({
            "loja": loja_nome, "desconto": c.get("couponDiscountShort") or "desconto",
            "titulo": c.get("couponTitle") or "", "codigo": c["couponCode"].strip(),
            "ate": c.get("couponUntil"), "link": link,
        })
        msg_grupo = None
        if grupo_tg and link:
            msg_grupo = (tg.mensagem(grupo_tg, textos["telegram"], previa=False) or {}).get("message_id")
        if admin:
            tg.mensagem(admin, textos["telegram"],
                        Telegram.botoes([("Mandar no WhatsApp", posts.link_whatsapp(textos["whatsapp"]))]),
                        previa=False)
        estado["cupons"][str(c["couponId"])] = {
            "id": str(c["couponId"]), "titulo": c.get("couponTitle") or "", "cupom": c["couponCode"].strip(),
            "loja_param": loja_param, "ate": c.get("couponUntil"), "quando": agora.isoformat(),
            "msg_grupo": msg_grupo, "foto": False, "texto_tg": textos["telegram"],
        }
        dia["cupons"] += 1
        print(f"  🎟️ cupom: {c['couponCode']} ({loja_nome})")


# ------------------------------------------------------------------ termômetro
def postar_termometro(tg: Telegram, estado: dict, cfg: dict, agora: datetime, admin, grupo_tg) -> None:
    """Uma vez por dia: diz se creatina e whey estão baratos ou se é pra segurar a carteira."""
    tcfg = cfg.get("termometro") or {}
    hoje = agora.date().isoformat()
    if not tcfg.get("ligado", True) or agora.hour < int(tcfg.get("hora", 12)):
        return
    if estado.get("termometro_postado") == hoje:
        return
    dados = estado.get("termometro") or {}
    ontem = (agora - timedelta(days=1)).date().isoformat()
    linhas = {}
    for tipo in ("creatina", "whey"):
        r = (dados.get(hoje) or {}).get(tipo) or (dados.get(ontem) or {}).get(tipo)
        if r:
            linhas[tipo] = r
    if not linhas:
        print("Termômetro: sem preço de creatina nem de whey pra comparar hoje.")
        return
    textos = posts.montar_termometro(linhas, cfg)
    if grupo_tg:
        tg.mensagem(grupo_tg, textos["telegram"], previa=False)
    if admin:
        tg.mensagem(admin, textos["telegram"],
                    Telegram.botoes([("Mandar no WhatsApp", posts.link_whatsapp(textos["whatsapp"]))]),
                    previa=False)
    estado["termometro_postado"] = hoje
    print("  🌡️ termômetro postado")


# ------------------------------------------------------------------ principal
def main() -> int:
    cfg = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
    segredos = {k: (os.environ.get(k) or "").strip() or None for k in
                ("TELEGRAM_TOKEN", "TELEGRAM_ADMIN_ID", "TELEGRAM_GRUPO_ID",
                 "AMAZON_TAG", "SHOPEE_APP_ID", "SHOPEE_SECRET")}
    teste = os.environ.get("TESTE") == "1"
    tg = Telegram(segredos["TELEGRAM_TOKEN"], teste=teste)
    admin, grupo_tg = segredos["TELEGRAM_ADMIN_ID"], segredos["TELEGRAM_GRUPO_ID"]
    if teste:
        admin, grupo_tg = admin or "ADMIN", grupo_tg or "GRUPO"
    agora = datetime.now(TZ)
    estado = carregar_estado()
    print(f"🐀 Rato de Promo — rodada de {agora:%d/%m %H:%M}{' (TESTE)' if teste else ''}")

    responder_comandos(tg, estado)
    if not segredos["TELEGRAM_TOKEN"] and not teste:
        print("Falta o TELEGRAM_TOKEN nos Secrets do GitHub.")
        return 1
    if not admin:
        print("Falta o TELEGRAM_ADMIN_ID: manda /start pro teu bot no Telegram, roda o robô de novo "
              "e ele te responde com o número.")
        salvar_estado(estado)
        return 0

    pb = Promobit()
    conferir_esgotados(pb, tg, estado, cfg, agora, admin, grupo_tg)

    if cfg["horario"]["inicio"] <= agora.hour < cfg["horario"]["fim"]:
        dia = contagem_do_dia(estado, agora.date().isoformat())
        vagas = min(cfg["posts_por_rodada"], cfg["posts_por_dia"] - dia["total"])
        print("Caçando ofertas…")
        aprovados = cacar_ofertas(pb, estado, cfg, agora, detalhar=vagas > 0)
        if vagas > 0:
            escolhidos = escolher(aprovados, dia, cfg, vagas)
            print(f"{len(aprovados)} aprovadas, {len(escolhidos)} escolhidas")
            for item in escolhidos:
                postar_oferta(item, pb, tg, estado, cfg, segredos, agora, admin, grupo_tg)
        else:
            print("Limite de posts do dia atingido.")
        print("Caçando cupons…")
        postar_cupons(pb, tg, estado, cfg, segredos, agora, admin, grupo_tg)
        postar_termometro(tg, estado, cfg, agora, admin, grupo_tg)
    else:
        print("Fora do horário de postar.")

    limpar(estado, agora, cfg)
    if not teste:
        salvar_estado(estado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
