"""Análise das ofertas: tipo de produto, peso, preço por dose, filtros e nota.

A ideia é simples: só passa oferta que é boa de verdade.
- Creatina e whey: preço por dose abaixo do teto da config e marca confiável.
- Tudo: preço perto do menor já registrado (histórico de preço do Promobit).
- Sem histórico: só passa com desconto alto e aprovação da galera.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field


def normalizar(texto: str | None) -> str:
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto.lower()).strip()


_PESO = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|kgs|kilos?|quilos?|lbs?|g|gr|grs|gramas)(?![a-z])")
_KIT = [
    re.compile(r"\bkit\s*(?:com\s*)?(\d{1,2})\b"),
    re.compile(r"\bcombo\s*(?:com\s*)?(\d{1,2})\b"),
    re.compile(r"\bleve\s*(\d)\b"),
    re.compile(r"\b(\d{1,2})\s*x\s*(?=\d)"),
    re.compile(r"(?:^|\s)(\d)\s*x\s"),
    re.compile(r"\b(\d{1,2})\s*(?:unidades|unid|potes)\b"),
]
_CAPSULAS = re.compile(r"\b\d{2,4}\s*(?:caps|capsulas|comprimidos|tabletes|tabs)\b")
_LIQUIDO = re.compile(r"\b\d+\s*ml\b")


def peso_total_gramas(titulo: str) -> float | None:
    """Peso total do produto em gramas (já multiplicado se for kit)."""
    t = normalizar(titulo)
    gramas = None
    for numero, unidade in _PESO.findall(t):
        valor = float(numero.replace(",", "."))
        if unidade.startswith(("kg", "kilo", "quilo")):
            valor *= 1000
        elif unidade.startswith("lb"):
            valor *= 453.6
        if valor >= 100:  # ignora "5g por dose", "30g de proteína" etc.
            gramas = valor
            break
    if gramas is None:
        return None
    for padrao in _KIT:
        achou = padrao.search(t)
        if achou:
            qtd = int(achou.group(1))
            if 1 < qtd <= 10:
                gramas *= qtd
            break
    return gramas


def achar_marca(titulo: str, marcas: list[str]) -> str | None:
    t = f" {normalizar(titulo)} "
    for marca in marcas:
        m = normalizar(marca)
        if re.search(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])", t):
            return marca
    return None


def tipo_suplemento(titulo: str) -> str:
    t = normalizar(titulo)
    if "creatina" in t or "creatine" in t:
        return "creatina"
    if "whey" in t or ("proteina" in t and ("isolad" in t or "concentrad" in t)):
        return "whey"
    return "suplemento"


@dataclass
class Avaliacao:
    grupo: str
    tipo: str
    marca: str | None = None
    gramas: float | None = None
    doses: float | None = None
    preco_dose: float | None = None
    dose_g: float | None = None
    nota: float = 0.0
    destaque: str | None = None
    rejeitada: str | None = None
    motivos: list[str] = field(default_factory=list)

    @property
    def aprovada(self) -> bool:
        return self.rejeitada is None


def _rejeita(av: Avaliacao, motivo: str) -> Avaliacao:
    av.rejeitada = motivo
    return av


def triagem(oferta: dict, grupo: str, cfg: dict) -> Avaliacao:
    """Filtros baratos, sem abrir a página da oferta."""
    titulo = oferta.get("offerTitle") or ""
    t = normalizar(titulo)
    preco = float(oferta.get("offerPrice") or 0)
    tipo = tipo_suplemento(titulo) if grupo == "suplementos" else "fitness"
    av = Avaliacao(grupo=grupo, tipo=tipo)

    if preco <= 0:
        return _rejeita(av, "sem preço")

    for palavra in cfg["ignorar_palavras"].get(grupo, []) + cfg["ignorar_palavras"].get("todos", []):
        if re.search(rf"(?<![a-z]){re.escape(normalizar(palavra))}", t):
            return _rejeita(av, f"palavra ignorada: {palavra}")

    if grupo == "fitness":
        palavras = cfg["fitness"]["palavras_obrigatorias"]
        if not any(normalizar(p) in t for p in palavras):
            return _rejeita(av, "não é roupa fitness nem tênis")

    av.marca = achar_marca(titulo, cfg["marcas_confiaveis"][grupo])
    if not av.marca:
        return _rejeita(av, "marca fora da lista de confiáveis")

    if tipo in ("creatina", "whey"):
        if _LIQUIDO.search(t):
            return _rejeita(av, "bebida pronta")
        if tipo == "creatina" and _CAPSULAS.search(t) and not cfg["creatina_aceita_capsulas"]:
            return _rejeita(av, "creatina em cápsula")
        gramas = peso_total_gramas(titulo)
        if not gramas:
            return _rejeita(av, "não deu pra ler o peso no título")
        av.gramas = gramas
        av.dose_g = float(cfg["dose_gramas"][tipo])
        av.doses = gramas / av.dose_g
        av.preco_dose = preco / av.doses
        if av.preco_dose / float(cfg["preco_max_por_dose"][tipo]) > 1.25:
            return _rejeita(av, f"dose cara: R$ {av.preco_dose:.2f}")
    return av


def avaliar(oferta: dict, detalhes: dict | None, grupo: str, cfg: dict) -> Avaliacao:
    """Dá nota pra oferta. `detalhes` é a página da oferta (pode ser None)."""
    av = triagem(oferta, grupo, cfg)
    if not av.aprovada:
        return av
    tipo = av.tipo
    preco = float(oferta.get("offerPrice") or 0)

    ref = (detalhes or {}).get("referencePrices") or {}
    ref_min = float(ref.get("minPrice") or 0)
    ref_max = float(ref.get("maxPrice") or 0)
    q_min = preco / ref_min if ref_min > 0 else None

    # ---- preço por dose (creatina e whey)
    if tipo in ("creatina", "whey"):
        teto = float(cfg["preco_max_por_dose"][tipo])
        r = av.preco_dose / teto
        menor_de_sempre = q_min is not None and q_min <= 1.03
        if r > 1.0 and not (menor_de_sempre and r <= 1.25):
            return _rejeita(av, f"dose cara: R$ {av.preco_dose:.2f}")
        if r <= 0.7:
            av.nota += 40
        elif r <= 0.85:
            av.nota += 28
        elif r <= 1.0:
            av.nota += 15
        av.nota += 10  # foco do grupo: whey e creatina
        av.motivos.append(f"dose R$ {av.preco_dose:.2f}")
        if r <= 0.8:
            av.destaque = "Uma das doses mais baratas do mercado"

    # ---- histórico de preço
    if q_min is not None:
        if q_min <= 1.01:
            av.nota += 40
            av.destaque = "Menor preço já registrado"
        elif q_min <= 1.05:
            av.nota += 30
            av.destaque = av.destaque or "Pertinho do menor preço já registrado"
        elif q_min <= 1.12:
            av.nota += 12
        elif q_min > cfg["maximo_acima_do_menor_preco"]:
            return _rejeita(av, f"caro perto do histórico (menor já visto R$ {ref_min:.2f})")
        if ref_max > preco:
            av.nota += min(20.0, (1 - preco / ref_max) * 50)
        av.motivos.append(f"histórico {ref_min:.2f}–{ref_max:.2f}")
    elif tipo not in ("creatina", "whey"):
        desconto = float(oferta.get("offerDiscontPercentage") or 0)
        if desconto < cfg["desconto_minimo_sem_historico"]:
            return _rejeita(av, f"sem histórico e desconto de só {desconto:.0f}%")
        av.nota += min(25.0, desconto * 0.5)

    # ---- vendedor
    vendedor = (detalhes or {}).get("storeMarketplace") or {}
    if vendedor and cfg["exigir_vendedor_verificado"] and not vendedor.get("isMarketplaceVerified"):
        return _rejeita(av, "vendedor de marketplace não verificado")

    # ---- aprovação da galera
    status = oferta.get("offerStatusName") or ""
    if status == "TOP_OFFER":
        av.nota += 8
    elif status == "RECENTS":
        av.nota -= 3
    av.nota += min(10, int(oferta.get("offerLikes") or 0))
    notas = oferta.get("ratings") or {}
    av.nota += min(6, 2 * (int(notas.get("great") or 0) + int(notas.get("amazing") or 0)))

    if av.nota < cfg["nota_minima"]:
        return _rejeita(av, f"nota baixa ({av.nota:.0f})")
    return av


def preco_antigo_confiavel(oferta: dict, detalhes: dict | None) -> float | None:
    """Só mostra o 'de' riscado se ele não for inflado (até 5% acima do maior preço já visto)."""
    preco = float(oferta.get("offerPrice") or 0)
    antigo = float(oferta.get("offerOldPrice") or 0)
    ref_max = float(((detalhes or {}).get("referencePrices") or {}).get("maxPrice") or 0)
    if antigo <= preco * 1.05:
        return None
    if ref_max <= 0 or antigo > ref_max * 1.05:
        return None
    return antigo


def chave_produto(loja: str, titulo: str) -> str:
    t = re.sub(r"[^a-z0-9 ]", "", normalizar(titulo))
    return f"{loja}:{t[:70]}"


def limite_por_porcentagem(pct: float, total: int) -> int:
    return math.ceil(pct / 100 * (total + 1))
