"""
K8s Sentinel - 檢查模組基礎類

定義所有檢查模組的統一介面
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """檢查結果"""

    module: str
    status: str  # "ok" | "warning" | "error"
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    affected_nodes: Optional[List[str]] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()
        if self.affected_nodes is None:
            self.affected_nodes = []

    def is_healthy(self) -> bool:
        """是否健康"""
        return self.status == "ok"

    def needs_fix(self) -> bool:
        """是否需要修復"""
        return self.status in ["warning", "error"]

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典"""
        return {
            "module": self.module,
            "status": self.status,
            "message": self.message,
            "details": self.details or {},
            "timestamp": self.timestamp,
            "affected_nodes": self.affected_nodes,
        }


@dataclass
class FixResult:
    """修復結果"""

    module: str
    success: bool
    message: str
    fixed_nodes: List[str]
    failed_nodes: List[str]
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典"""
        return {
            "module": self.module,
            "success": self.success,
            "message": self.message,
            "fixed_nodes": self.fixed_nodes,
            "failed_nodes": self.failed_nodes,
            "details": self.details or {},
            "timestamp": self.timestamp,
        }


class BaseCheck(ABC):
    """檢查模組基礎類"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @property
    @abstractmethod
    def name(self) -> str:
        """模組名稱"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """模組描述"""
        pass

    @abstractmethod
    def check(self) -> CheckResult:
        """執行檢查"""
        pass

    @abstractmethod
    def can_auto_fix(self) -> bool:
        """是否支援自動修復"""
        pass

    @abstractmethod
    def fix(self, check_result: CheckResult) -> FixResult:
        """執行修復"""
        pass

    def validate_config(self) -> bool:
        """驗證配置"""
        return True

    def get_metadata(self) -> Dict[str, Any]:
        """獲取模組元數據"""
        return {
            "name": self.name,
            "description": self.description,
            "can_auto_fix": self.can_auto_fix(),
            "config_required": list(self.config.keys()),
        }


class CheckRegistry:
    """檢查模組註冊表"""

    _checks: Dict[str, BaseCheck] = {}

    @classmethod
    def register(cls, check: BaseCheck) -> None:
        """註冊檢查模組"""
        cls._checks[check.name] = check
        logger.info(f"Registered check module: {check.name}")

    @classmethod
    def get(cls, name: str) -> Optional[BaseCheck]:
        """獲取檢查模組"""
        return cls._checks.get(name)

    @classmethod
    def list_all(cls) -> List[str]:
        """列出所有模組"""
        return list(cls._checks.keys())

    @classmethod
    def get_all(cls) -> List[BaseCheck]:
        """獲取所有模組"""
        return list(cls._checks.values())
