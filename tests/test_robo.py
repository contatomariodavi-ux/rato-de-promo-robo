from pathlib import Path

import pytest
import yaml

from robo import afiliados, analise, posts
from robo.analise import Avaliacao
from robo.main import escolher, oferta_acabou

CFG = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8"))


def oferta(titulo, preco, antigo=0, loja="mercado-livre", status="APPROVED", likes=1, desc=0, oid=1):
    return {
        "offerId": oid, "offerTitle": titulo, "offerPrice": preco, "offerOldPrice": antigo,
        "storeParam": loja, "offerStatusName": status, "offerLikes": likes,
        "offerDiscontPercentage": desc, "ratings": {}, "offerSlug": f"x-{oid}",
    }


def det(minimo, maximo, verificado=True):
    return {"referencePrices": {"minPrice": minimo, "maxPrice": maximo},
            "storeMarketplace": {"isMarketplaceVerified": verificado}}


@pytest.mark.parametrize("titulo,gramas", [
    ("Creatina Monohidratada 1kg Max Titanium", 1000),
    ("Kit 2 Creatina 300g Growth", 600),
    ("Kit com 3 Creatina Dux 250g", 750),
    ("Whey Protein Gold Standard 2lbs", 907.2),
    ("Creatina 1,2kg Integralmedica", 1200),
    ("Whey 5g por dose 900g Dux", 900),
    ("Creatina Soldiers Nutrition 1200g", 1200),
    ("2x Creatina 500g Probiótica", 1000),
    ("Whey Protein sem peso no título", None),
])
def test_peso(titulo, gramas):
    assert analise.peso_total_gramas(titulo) == (pytest.approx(gramas) if gramas else None)


def test_creatina_boa_passa_com_preco_por_dose():
    av = analise.avaliar(oferta("Creatina Monohidratada 1kg Max Titanium", 79.0), det(78, 140), "suplementos", CFG)
    assert av.aprovada, av.rejeitada
    assert av.tipo == "creatina"
    assert av.preco_dose == pytest.approx(79 / (1000 / 3))
    assert av.destaque == "Uma das doses mais baratas do mercado"


def test_creatina_cara_reprovada():
    av = analise.avaliar(oferta("Creatina Max Titanium 300g", 59.9), det(55, 90), "suplementos", CFG)
    assert not av.aprovada and "dose cara" in av.rejeitada


def test_marca_desconhecida_reprovada():
    av = analise.avaliar(oferta("Creatina Pura Marca Qualquer 1kg", 49.0), det(49, 90), "suplementos", CFG)
    assert not av.aprovada and "marca" in av.rejeitada


def test_barrinha_de_whey_reprovada():
    av = analise.triagem(oferta("Whey Protein Bold Barra 12 un 60g", 48), "suplementos", CFG)
    assert not av.aprovada


def test_caro_perto_do_historico_reprovado():
    av = analise.avaliar(oferta("Pré-Treino Growth 300g", 120), det(80, 130), "suplementos", CFG)
    assert not av.aprovada and "histórico" in av.rejeitada


def test_vendedor_nao_verificado_reprovado():
    av = analise.avaliar(oferta("Creatina Monohidratada 1kg Dux", 79.0), det(79, 150, verificado=False),
                         "suplementos", CFG)
    assert not av.aprovada and "vendedor" in av.rejeitada


def test_tenis_bom_passa_e_chinelo_nao():
    ok = analise.avaliar(oferta("Tênis Nike Revolution 7 Masculino", 199.0), det(195, 399), "fitness", CFG)
    assert ok.aprovada, ok.rejeitada
    assert ok.destaque == "Pertinho do menor preço já registrado"
    ruim = analise.triagem(oferta("Chinelo Nike Victori One", 99.0), "fitness", CFG)
    assert not ruim.aprovada


def test_fitness_sem_historico_precisa_de_desconto_alto():
    fraco = analise.avaliar(oferta("Legging Live! Fit", 99, desc=20), {}, "fitness", CFG)
    assert not fraco.aprovada
    forte = analise.avaliar(oferta("Legging Live! Fit", 99, desc=55, likes=5, status="TOP_OFFER"), {}, "fitness", CFG)
    assert forte.aprovada, forte.rejeitada


def test_preco_antigo_inflado_nao_aparece():
    o = oferta("x", 78.9, antigo=299.9)
    assert analise.preco_antigo_confiavel(o, det(78, 140)) is None
    o2 = oferta("x", 100, antigo=139)
    assert analise.preco_antigo_confiavel(o2, det(95, 140)) == 139


def _av(grupo, nota):
    return Avaliacao(grupo=grupo, tipo="x", nota=nota)


def test_mix_70_30_e_limite_shopee():
    aprovados = []
    for i in range(10):
        aprovados.append((_av("suplementos", 90 - i), oferta(f"sup {i}", 10, oid=i), {}))
        aprovados.append((_av("fitness", 95 - i), oferta(f"fit {i}", 10, oid=100 + i), {}))
        aprovados.append((_av("academia", 99 - i), oferta(f"acad {i}", 10, oid=200 + i), {}))
    dia = {"total": 0, "suplementos": 0, "fitness": 0, "academia": 0, "shopee": 0, "cupons": 0}
    esc = escolher(aprovados, dia, CFG, 10)
    grupos = [e[0].grupo for e in esc]
    assert (grupos.count("suplementos"), grupos.count("fitness"), grupos.count("academia")) == (7, 2, 1)
    # sem nada de academia, o suplemento ocupa a vaga
    sem_acad = [a for a in aprovados if a[0].grupo != "academia"]
    grupos = [e[0].grupo for e in escolher(sem_acad, dict(dia), CFG, 10)]
    assert grupos.count("suplementos") >= 7

    so_shopee = [(_av("suplementos", 90 - i), oferta(f"s {i}", 10, loja="shopee", oid=i), {}) for i in range(10)]
    esc = escolher(so_shopee, dict(dia), CFG, 10)
    assert len(esc) <= 4  # no máximo ~30% do dia


def test_post_whatsapp_formatado():
    t = posts.montar_oferta({
        "titulo": "Creatina Monohidratada 1kg Max Titanium", "preco": 79.0, "antigo": 129.9,
        "preco_dose": 0.237, "dose_g": 3, "cupom": "RATO10", "destaque": "Menor preço já registrado",
        "loja": "Amazon", "vendedor": None, "link": "https://www.amazon.com.br/dp/B000000000?tag=rato-20",
    })
    wa = t["whatsapp"]
    assert "~R$ 129,90~ por *R$ 79,00*" in wa
    assert "💪 R$ 0,24 a dose" in wa
    assert "Preço e estoque" not in wa
    assert "🏷️ Usa o cupom *RATO10* no carrinho" in wa
    assert wa.startswith("🐀 *")
    assert "<s>R$ 129,90</s>" in t["telegram"]
    assert posts.link_whatsapp(wa).startswith("https://wa.me/?text=%F0%9F%90%80")


def test_esgotado():
    t = posts.montar_esgotado("Creatina 1kg", "RATO10")
    assert t["whatsapp"].startswith("❌ *CUPOM ESGOTADO!*")
    assert "<b>RATO10</b>" in t["telegram"]
    t2 = posts.montar_esgotado("Creatina 1kg", None)
    assert "OFERTA ESGOTADA" in t2["whatsapp"]


def test_link_amazon_troca_tag():
    l = afiliados.link_amazon("https://www.amazon.com.br/dp/B0GTRNTYDH?tag=promobit-m-20", "ratodepromo-20")
    assert l.url == "https://www.amazon.com.br/dp/B0GTRNTYDH?tag=ratodepromo-20" and not l.manual
    sem_tag = afiliados.link_amazon("https://www.amazon.com.br/dp/B0GTRNTYDH", None)
    assert sem_tag.manual


def test_datas_e_status():
    d = posts.ler_data("2026-12-17T23:59:59-0300")
    assert d.utcoffset().total_seconds() == -3 * 3600
    assert oferta_acabou(404, None)
    assert oferta_acabou(200, {"offerStatusName": "EXPIRED"})
    assert not oferta_acabou(200, {"offerStatusName": "TOP_OFFER"})


def test_aviso_de_esgotado(capsys):
    from datetime import datetime, timedelta
    from robo.main import TZ, conferir_esgotados
    from robo.telegram import Telegram

    class PBFalso:
        def detalhes(self, slug):
            return (404, None) if slug == "sumiu" else (200, {"offerStatusName": "APPROVED"})

        def cupons(self, loja):
            return []

    agora = datetime.now(TZ)
    estado = {
        "postados": {
            "1": {"titulo": "Creatina 1kg Dux", "slug": "sumiu", "cupom": "RATO10",
                  "quando": (agora - timedelta(hours=2)).isoformat(), "msg_grupo": 55, "foto": True, "texto_tg": "x"},
            "2": {"titulo": "Whey 900g Growth", "slug": "ativa", "cupom": None,
                  "quando": (agora - timedelta(hours=2)).isoformat(), "msg_grupo": 56, "foto": True, "texto_tg": "y"},
        },
        "cupons": {
            "9": {"id": "9", "titulo": "30% em Esportes", "cupom": "MELI30", "loja_param": "mercado-livre",
                  "ate": (agora - timedelta(minutes=5)).isoformat(), "quando": (agora - timedelta(days=1)).isoformat(),
                  "msg_grupo": None, "texto_tg": "z"},
        },
    }
    conferir_esgotados(PBFalso(), Telegram(None, teste=True), estado, CFG, agora, "ADMIN", "GRUPO")
    assert estado["postados"]["1"]["esgotado"] is True
    assert not estado["postados"]["2"].get("esgotado")
    assert estado["cupons"]["9"]["esgotado"] is True
    saida = capsys.readouterr().out
    assert "editMessageCaption" in saida and "CUPOM ESGOTADO" in saida


def test_titulo_arrumado():
    t = posts.montar_oferta({"titulo": "creatina monohidratada soldiers nutrition 1200g", "preco": 86.35,
                             "loja": "Amazon", "link": None})
    assert "\n*Creatina Monohidratada Soldiers Nutrition 1,2kg*\n" in t["whatsapp"]
    assert t["whatsapp"].endswith("👉 COLE_SEU_LINK_AQUI")
    t2 = posts.montar_oferta({"titulo": "Whey Protein Gold Standard 100% 2,27kg - Optimum Nutrition", "preco": 300,
                              "loja": "Amazon", "link": "x"})
    assert "*Whey Protein Gold Standard 100% 2,27kg - Optimum Nutrition*" in t2["whatsapp"]


def test_termometro_caro_e_barato(capsys):
    from datetime import datetime
    from robo.main import TZ, postar_termometro, registrar_termometro
    from robo.telegram import Telegram

    agora = datetime(2026, 11, 18, 12, 30, tzinfo=TZ)
    estado = {}
    registrar_termometro(estado, oferta("Creatina Monohidratada 1kg Max Titanium", 129.9, loja="amazon"), CFG, agora)
    registrar_termometro(estado, oferta("Creatina Monohidratada 1kg Growth", 119.9, loja="amazon"), CFG, agora)
    registrar_termometro(estado, oferta("Whey Protein Concentrado 900g Dux", 99.0, loja="mercado-livre"), CFG, agora)
    registrar_termometro(estado, oferta("Creatina Marca Desconhecida 1kg", 40.0, loja="amazon"), CFG, agora)
    dia = estado["termometro"]["2026-11-18"]
    assert dia["creatina"]["dose"] == pytest.approx(119.9 / (1000 / 3), abs=1e-3)  # a desconhecida não conta
    postar_termometro(Telegram(None, teste=True), estado, CFG, agora, "ADMIN", "GRUPO")
    saida = capsys.readouterr().out
    assert "Termômetro do Rato" in saida and "Tá cara, não compra agora!" in saida and "R$ 119,90 o quilo" in saida
    assert "Tá barato, pode comprar!" in saida
    assert estado["termometro_postado"] == "2026-11-18"
    postar_termometro(Telegram(None, teste=True), estado, CFG, agora, "ADMIN", "GRUPO")  # não repete no dia
    assert "Termômetro do Rato" not in capsys.readouterr().out

    tudo_caro = posts.montar_termometro({"creatina": {"dose": 0.40}, "whey": {"dose": 5.5}}, CFG)["whatsapp"]
    assert tudo_caro.startswith("🐀 *Galera, segura a carteira!*")


def test_academia_sem_lista_de_marca():
    ok = analise.avaliar(oferta("Luva de Academia Musculação Couro com Munhequeira", 39.9), det(39, 89), "academia", CFG)
    assert ok.aprovada, ok.rejeitada
    fora = analise.triagem(oferta("Fone de Ouvido Bluetooth", 99.0), "academia", CFG)
    assert not fora.aprovada
    caro = analise.avaliar(oferta("Kettlebell 12kg Emborrachado", 199.0), det(120, 210), "academia", CFG)
    assert not caro.aprovada and "histórico" in caro.rejeitada


def test_cupom_afiliado_e_anuncio():
    from robo.main import cupom_afiliado
    cfg = dict(CFG, cupons_afiliado=[
        {"codigo": "VELHO", "loja": "mercado-livre", "ate": "2020-01-01"},
        {"codigo": "MLSAUDE", "loja": "mercado-livre", "palavras": ["whey", "creatina"]},
    ])
    assert cupom_afiliado(oferta("Creatina 1kg Dux", 80), cfg) == "MLSAUDE"
    assert cupom_afiliado(oferta("Tênis Nike", 200), cfg) is None
    assert cupom_afiliado(oferta("Creatina 1kg Dux", 80, loja="amazon"), cfg) is None
    t = posts.montar_oferta({"titulo": "Creatina 1kg Dux", "preco": 80, "cupom": "MLSAUDE", "loja": "Mercado Livre",
                             "link": None, "anuncio": True})
    assert t["whatsapp"].endswith("_Anúncio_") and t["telegram"].endswith("<i>Anúncio</i>")


def test_cupom_ml_automatico_por_grupo():
    from datetime import datetime
    from robo.main import TZ, cupons_ml_por_grupo

    class PBFalso:
        def cupons(self, loja):
            return [
                {"couponCode": "POUPAAGORA25", "couponStatusName": "APPROVED", "couponDiscountShort": "25% OFF",
                 "couponTitle": "Cupom Mercado Livre: 25% OFF em Casa, Saúde e mais", "couponUntil": "2026-12-17T23:59:59-0300"},
                {"couponCode": "MELIVIP25", "couponStatusName": "APPROVED", "couponDiscountShort": "25% OFF",
                 "couponTitle": "25% OFF em Casa, Esportes e mais", "couponUntil": None},
                {"couponCode": "MELIPROMOBIT", "couponStatusName": "APPROVED", "couponDiscountShort": "40% OFF",
                 "couponTitle": "Cupom exclusivo Saúde", "couponUntil": None},
                {"couponCode": "VENCIDO", "couponStatusName": "APPROVED", "couponDiscountShort": "50% OFF",
                 "couponTitle": "50% em Saúde", "couponUntil": "2026-01-01T00:00:00-0300"},
            ]

    mapa = cupons_ml_por_grupo(PBFalso(), CFG, datetime(2026, 11, 18, 10, tzinfo=TZ))
    assert mapa == {"suplementos": "POUPAAGORA25", "fitness": "MELIVIP25", "academia": "MELIVIP25"}
    t = posts.montar_oferta({"titulo": "Creatina 1kg Dux", "preco": 80, "cupom": "POUPAAGORA25", "cupom_teste": True,
                             "loja": "Mercado Livre", "link": None})
    assert "Testa o cupom *POUPAAGORA25* no carrinho" in t["whatsapp"]
