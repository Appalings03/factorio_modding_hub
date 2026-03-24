"""
scrapers/base_scraper.py
========================
Classe de base pour tous les scrapers.
Fournit : cache, logging, retry HTTP, et interface commune.
"""

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("factorio_hub.scrapers")


class BaseScraper(ABC):
    """
    Classe abstraite commune à tous les scrapers.

    Sous-classes concrètes :
    - RawDataScraper   (scrapers/raw_data_scraper.py)
    - ApiDocsParser    (scrapers/api_docs_scraper.py)
    - GitHubScraper    (scrapers/github_scraper.py)
    """

    def __init__(self, cache_dir: Path, force_refresh: bool = False):
        self.cache_dir     = Path(cache_dir)
        self.force_refresh = force_refresh
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = self._build_session()

    # ------------------------------------------------------------------ #
    # Session HTTP avec retry automatique                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_session() -> requests.Session:
        """
        Session requests avec retry exponentiel sur les erreurs réseau.
        Retry sur : 429 (rate limit), 500, 502, 503, 504.
        """
        session = requests.Session()
        retry = Retry(
            total=4,
            backoff_factor=1.5,          # 1.5s, 3s, 4.5s, 6s
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://",  adapter)
        session.headers["User-Agent"] = (
            "factorio-modding-hub/1.0 "
            "(personal modding tool; github.com/wube/factorio-data)"
        )
        return session

    # ------------------------------------------------------------------ #
    # Cache                                                                #
    # ------------------------------------------------------------------ #

    def _cache_path(self, filename: str) -> Path:
        return self.cache_dir / filename

    def _is_cached(self, filename: str) -> bool:
        p = self._cache_path(filename)
        return p.exists() and p.stat().st_size > 0 and not self.force_refresh

    def _read_cache_json(self, filename: str) -> dict | list:
        return json.loads(self._cache_path(filename).read_text(encoding="utf-8"))

    def _write_cache(self, filename: str, data: bytes) -> None:
        self._cache_path(filename).write_bytes(data)

    def _write_cache_json(self, filename: str, data: dict | list) -> None:
        self._cache_path(filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_cache_text(self, filename: str, text: str) -> None:
        self._cache_path(filename).write_text(text, encoding="utf-8")

    @staticmethod
    def sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    # ------------------------------------------------------------------ #
    # Requêtes HTTP                                                        #
    # ------------------------------------------------------------------ #

    def get(self, url: str, timeout: int = 60, stream: bool = False,
            **kwargs) -> requests.Response:
        """
        GET avec logging. Lève requests.HTTPError sur 4xx/5xx.
        """
        logger.debug("GET %s", url)
        resp = self.session.get(url, timeout=timeout, stream=stream, **kwargs)
        resp.raise_for_status()
        return resp

    def get_json(self, url: str, cache_filename: str | None = None,
                 timeout: int = 60) -> dict | list:
        """
        GET JSON avec cache optionnel.
        Si cache_filename est fourni et que le cache est valide, retourne le cache.
        """
        if cache_filename and self._is_cached(cache_filename):
            logger.debug("Cache hit : %s", cache_filename)
            return self._read_cache_json(cache_filename)

        resp = self.get(url, timeout=timeout)
        data = resp.json()

        if cache_filename:
            self._write_cache_json(cache_filename, data)
            logger.debug("Cache écrit : %s", cache_filename)

        return data

    def get_bytes(self, url: str, cache_filename: str | None = None,
                  timeout: int = 120) -> bytes:
        """GET binaire avec cache optionnel."""
        if cache_filename and self._is_cached(cache_filename):
            logger.debug("Cache hit : %s", cache_filename)
            return self._cache_path(cache_filename).read_bytes()

        logger.info("Téléchargement : %s", url)
        resp = self.get(url, timeout=timeout, stream=True)
        data = resp.content

        if cache_filename:
            self._write_cache(cache_filename, data)
            logger.debug("Cache écrit : %s (%d octets)", cache_filename, len(data))

        return data

    # ------------------------------------------------------------------ #
    # Interface abstraite                                                  #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def fetch(self) -> dict | list:
        """
        Point d'entrée principal du scraper.
        Retourne les données brutes prêtes à être parsées.
        """
        ...

    # ------------------------------------------------------------------ #
    # Utilitaires                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def sleep(seconds: float) -> None:
        """Pause de politesse entre les requêtes."""
        time.sleep(seconds)

    def invalidate_cache(self, filename: str) -> None:
        """Supprime un fichier de cache spécifique."""
        p = self._cache_path(filename)
        if p.exists():
            p.unlink()
            logger.info("Cache invalidé : %s", filename)