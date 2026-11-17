"""Conversa com a API do Telegram."""
from __future__ import annotations

import requests


class Telegram:
    def __init__(self, token: str | None, teste: bool = False):
        self.token = token
        self.teste = teste or not token
        self.base = f"https://api.telegram.org/bot{token}" if token else ""

    def _chamar(self, metodo: str, **dados) -> dict | None:
        if self.teste:
            print(f"  [TESTE] {metodo}: {str(dados.get('text') or dados.get('caption') or '')[:400]}")
            return {"message_id": 0}
        try:
            r = requests.post(f"{self.base}/{metodo}", json=dados, timeout=30)
            resp = r.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  ! Telegram {metodo} falhou: {e}")
            return None
        if not resp.get("ok"):
            print(f"  ! Telegram {metodo}: {resp.get('description')}")
            return None
        return resp.get("result")

    @staticmethod
    def botoes(*linhas: list[tuple[str, str]]) -> dict:
        return {"inline_keyboard": [[{"text": t, "url": u} for t, u in linha] for linha in linhas if linha]}

    def mensagem(self, chat_id, texto: str, botoes: dict | None = None, responder_a: int | None = None,
                 previa: bool = True) -> dict | None:
        dados = {
            "chat_id": chat_id,
            "text": texto,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": not previa},
        }
        if botoes:
            dados["reply_markup"] = botoes
        if responder_a:
            dados["reply_parameters"] = {"message_id": responder_a, "allow_sending_without_reply": True}
        return self._chamar("sendMessage", **dados)

    def foto(self, chat_id, foto_url: str, legenda: str, botoes: dict | None = None) -> dict | None:
        dados = {"chat_id": chat_id, "photo": foto_url, "caption": legenda[:1024], "parse_mode": "HTML"}
        if botoes:
            dados["reply_markup"] = botoes
        return self._chamar("sendPhoto", **dados)

    def editar(self, chat_id, message_id: int, texto: str, eh_foto: bool) -> dict | None:
        if eh_foto:
            return self._chamar("editMessageCaption", chat_id=chat_id, message_id=message_id,
                                caption=texto[:1024], parse_mode="HTML")
        return self._chamar("editMessageText", chat_id=chat_id, message_id=message_id,
                            text=texto, parse_mode="HTML")

    def novidades(self, offset: int) -> list[dict]:
        if self.teste:
            return []
        resp = self._chamar("getUpdates", offset=offset, timeout=0, allowed_updates=["message", "channel_post"])
        return resp or []
