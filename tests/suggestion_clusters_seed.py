"""Seeded Cluster entries for tests (no real people; business names only).

Use via the `seeded_clusters` fixture in tests/conftest.py, or call
`build_seeded_clusters()` directly.
"""

from datetime import date

from habitantes.domain.suggestions import ClusterEntry, ClusterMember, Kind


def build_seeded_clusters() -> list[ClusterEntry]:
    return [
        ClusterEntry(
            kind=Kind.MARKETS_AND_GROCERIES,
            label="Produtos brasileiros",
            thumbs_up=14,
            thumbs_down=1,
            last_date=date(2026, 5, 20),
            members=[
                ClusterMember(
                    name="Épicerie Tropical",
                    thumbs_up=9,
                    thumbs_down=0,
                    last_date=date(2026, 5, 20),
                    items=["polvilho", "farinha de mandioca", "massa de pastel"],
                ),
                ClusterMember(
                    name="Grand Frais",
                    thumbs_up=4,
                    thumbs_down=1,
                    last_date=date(2025, 11, 2),
                    items=["frutas", "carne"],
                ),
                ClusterMember(
                    name="Sabor do Brasil",
                    thumbs_up=1,
                    thumbs_down=0,
                    last_date=date(2023, 3, 14),
                    items=["guaraná", "pão de queijo"],
                    community_business=True,
                ),
            ],
            summary="Épicerie Tropical (9👍), Grand Frais (4👍/1👎), Sabor do Brasil (1👍)",
        ),
        ClusterEntry(
            kind=Kind.DENTISTS,
            label="Dentista de rotina",
            thumbs_up=7,
            thumbs_down=2,
            last_date=date(2026, 2, 8),
            members=[
                ClusterMember(
                    name="Cabinet Dentaire Alpes",
                    thumbs_up=5,
                    thumbs_down=0,
                    last_date=date(2026, 2, 8),
                    items=["limpeza dental", "consulta"],
                ),
                ClusterMember(
                    name="Clinique du Sourire",
                    thumbs_up=2,
                    thumbs_down=2,
                    last_date=date(2024, 6, 1),
                    items=["clareamento"],
                ),
            ],
            summary="Cabinet Dentaire Alpes (5👍), Clinique du Sourire (2👍/2👎)",
        ),
        ClusterEntry(
            kind=Kind.SALONS_AND_BEAUTY,
            label="Cabelo cacheado",
            thumbs_up=3,
            thumbs_down=0,
            last_date=date(2025, 9, 30),
            members=[
                ClusterMember(
                    name="Salon Boucles",
                    thumbs_up=3,
                    thumbs_down=0,
                    last_date=date(2025, 9, 30),
                    items=["corte de cabelo cacheado"],
                ),
            ],
            summary="Salon Boucles (3👍)",
        ),
    ]
