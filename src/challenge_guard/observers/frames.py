"""Frame observer (CG-008).

Classifica por HOST e forma. Nunca acessa conteudo cross-origin: o que existe
aqui e a URL do frame, se ele esta visivel e o tamanho.

Duas regras que evitam os falsos positivos mais comuns:

    iframe presente != challenge ativo
    widget residual depois de uma submissao confirmada nao rebaixa o resultado

A primeira e resolvida aqui (frame conta como sinal, nao como veredito); a
segunda pertence a policy, que nunca rebaixa `submission_confirmed`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..models import ChallengeType
from ..providers.registry import profile_for, profile_for_frame
from ..signals import ChallengeSignal, ChallengeSignalKind
from .base import ObserverResult

#: Abaixo disto o frame e considerado decorativo (selo de 1x1, tracking).
_MIN_CHALLENGE_SIDE = 40

#: Segmento de caminho que e um identificador opaco, nao estrutura.
#:
#: Achado real: o hCaptcha serve
#: `/captcha/v1/633567452af282a792b41ae854a73508f80017fa/static/...`, ou seja, o
#: token `se` da conta viaja NO CAMINHO. Registrar o caminho literal (a) vaza o
#: identificador e (b) faz o fingerprint mudar quando o provedor troca o id,
#: inventando rodada nova sem nada ter mudado de forma.
_OPAQUE_SEGMENT = re.compile(r"^(?:[0-9a-fA-F]{8,}|[A-Za-z0-9_-]{20,})$")


def path_shape(path: str) -> str:
    """Caminho com segmentos opacos trocados por `:id` — forma, nao identidade."""
    segments = [segment for segment in (path or "/").split("/") if segment]
    return "/" + "/".join(":id" if _OPAQUE_SEGMENT.match(segment) else segment for segment in segments)


@dataclass(frozen=True)
class FrameInfo:
    url: str
    visible: bool = True
    width: int = 0
    height: int = 0

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").casefold()

    @property
    def path(self) -> str:
        """Caminho literal. So para inspecao: NAO use em estrutura persistida."""
        return urlsplit(self.url).path or "/"

    @property
    def path_shape(self) -> str:
        """Caminho normalizado, seguro para estrutura e para o fingerprint."""
        return path_shape(self.path)

    @property
    def sizable(self) -> bool:
        return max(self.width, self.height) >= _MIN_CHALLENGE_SIDE


class FrameObserver:
    name = "frames"

    def observe(self, frames: list[FrameInfo]) -> ObserverResult:
        signals: list[ChallengeSignal] = []
        structure: list[str] = []
        challenge_type = ChallengeType.UNKNOWN
        for frame in frames:
            profile = profile_for_frame(frame.host, frame.path)
            if profile is None:
                continue
            # Forma entra no fingerprint sempre; o SINAL exige visibilidade e
            # tamanho plausivel, porque um iframe escondido nao bloqueia nada.
            structure.append(f"{frame.host}{frame.path_shape}")
            if not (frame.visible and frame.sizable):
                continue
            # Um match por CAMINHO e mais especifico que um marcador generico de
            # DOM: e ele que separa dois provedores que dividem o mesmo host. Por
            # isso pesa mais, senao o sinal generico do DOM venceria no merge e
            # Enterprise nunca seria identificado.
            specific = bool(profile.frame_paths) and any(
                re.match(pattern, frame.path) for pattern in profile.frame_paths
            )
            presented = any(
                re.match(pattern, frame.path) for pattern in profile.challenge_frame_paths
            )
            signals.append(
                ChallengeSignal(
                    kind=ChallengeSignalKind.CHALLENGE_VISIBLE,
                    source=self.name,
                    provider=profile.provider,
                    confidence=0.9 if presented else (0.85 if specific else 0.75),
                    detail=f"frame.{profile.provider.value}",
                )
            )
            if presented:
                # Desafio APRESENTADO: e interativo, independentemente do tipo
                # padrao do provider (que descreve o selo).
                challenge_type = ChallengeType.IMAGE_SELECTION
        if not signals:
            return ObserverResult(source=self.name, structure=tuple(structure))
        best = max(signals, key=lambda signal: signal.confidence)
        profile = profile_for(best.provider)
        if challenge_type is ChallengeType.UNKNOWN and profile is not None:
            challenge_type = profile.default_type
        return ObserverResult(
            source=self.name,
            signals=tuple(signals),
            provider=best.provider,
            challenge_type=challenge_type,
            structure=tuple(structure),
            confidence=best.confidence,
        )
