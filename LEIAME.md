# 🐀 Robô do Rato de Promo

Roda sozinho no GitHub, de hora em hora, das 7h às 23h. A cada rodada ele:

1. Caça as ofertas novas de creatina, whey, outros suplementos, tênis e roupa fitness que a galera postou e votou no Promobit, só de Amazon, Mercado Livre e Shopee.
2. Descarta o que não presta: marca fora da lista, vendedor não verificado, preço caro perto do histórico, desconto inflado, barrinha/bebida, creatina e whey com preço por dose acima do teto.
3. Escolhe as melhores respeitando 70% suplementos / 30% fitness e no máximo 30% de Shopee.
4. Posta no grupo do Telegram (quando o link de afiliado é automático) e te manda no privado o post pronto com o botão **📲 Mandar no WhatsApp**.
5. Caça cupom de esporte, saúde, suplemento e moda, posta enquanto vale e, quando esgota, marca o post como **❌ ESGOTADO** e te manda o aviso "cupom esgotado" pronto pro WhatsApp.

## Link de afiliado em cada loja

| Loja | Como fica |
|---|---|
| Amazon | Automático, com a tua tag (`AMAZON_TAG`). |
| Shopee | Automático depois que a Shopee liberar a API de afiliado (`SHOPEE_APP_ID` e `SHOPEE_SECRET`). Até lá, manual. |
| Mercado Livre | Manual: o ML não tem API de link de afiliado. O robô te manda o botão **Abrir no Mercado Livre**; no app você toca em Compartilhar, copia teu link e troca o `COLE_SEU_LINK_AQUI` no post. |

## Passo a passo (tudo pelo celular)

**1. Bot do Telegram**
- No Telegram, abre o **@BotFather**, manda `/newbot`, dá o nome *Rato de Promo* e um usuário terminado em `bot`.
- Ele te dá um **token**. Guarda (não manda pra ninguém).
- Cria o grupo do Rato de Promo no Telegram e adiciona o bot como **administrador**.

**2. GitHub**
- Cria conta em github.com e um repositório **privado** chamado `rato-de-promo-robo` com estes arquivos.
- Em **Settings › Secrets and variables › Actions › New repository secret**, cria:
  - `TELEGRAM_TOKEN` = o token do BotFather
  - `AMAZON_TAG` = tua tag de associado (ex.: `ratodepromo-20`) — quando a Amazon aprovar
  - `SHOPEE_APP_ID` e `SHOPEE_SECRET` — quando a Shopee liberar a API

**3. Descobrir os IDs**
- Manda `/start` pro teu bot no privado e `/id` dentro do grupo do Telegram.
- No GitHub: **Actions › Robô Rato de Promo › Run workflow**.
- O bot responde em cada chat com o número. Salva como secrets:
  - `TELEGRAM_ADMIN_ID` = o número da conversa privada
  - `TELEGRAM_GRUPO_ID` = o número do grupo (começa com `-`)

**4. Pronto.** Roda sozinho. Pra ver o que ele faria sem postar nada: Run workflow com **Modo teste** marcado e olha o log.

## Ajustes

Tudo no `config.yaml` (abre no GitHub e toca no lápis): mix, posts por dia, horário, teto de preço por dose, marcas confiáveis, palavras ignoradas, cupons, e o `link_padrao` (link de afiliado genérico do ML e da Shopee que vai nos posts de cupom).

A memória do robô (o que já postou, preços, contagem do dia) fica em `dados/estado.json`, salva sozinha a cada rodada.
