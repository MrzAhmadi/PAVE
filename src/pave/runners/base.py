from abc import ABC, abstractmethod
from typing import Optional


class ProxyRunner(ABC):
    @abstractmethod
    def __enter__(self) -> Optional[int]:
        ...

    @abstractmethod
    def __exit__(self, *args) -> None:
        ...
