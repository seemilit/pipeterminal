"""Feature-owned authorization translations for all existing UI languages."""

from common.i18n import register_messages


def install_translations() -> None:
    sources = (
        "授权", "当前权限：{0}", "免费版", "付费版", "授权状态：{0}",
        "未激活", "授权有效", "授权已过期", "授权尚未生效", "授权码无效", "尚未配置授权验证公钥",
        "开发模式：{0}", "全部功能", "模拟免费", "模拟有效", "模拟过期",
        "授权用户：{0}", "到期时间：{0}", "授权码", "请输入授权码", "激活", "移除授权",
        "授权变化将在重启后生效", "授权已保存，请重启应用后生效", "授权已移除，请重启应用后生效",
        "操作失败：{0}", "授权不可用",
    )
    translations = {
        "en": (
            "License", "Current access: {0}", "Free", "Paid", "License status: {0}",
            "Not activated", "Valid", "Expired", "Not yet valid", "Invalid license code", "License verification key is not configured",
            "Development mode: {0}", "All features", "Simulated free", "Simulated valid", "Simulated expired",
            "Licensed to: {0}", "Expires at: {0}", "License code", "Enter your license code", "Activate", "Remove license",
            "License changes take effect after restarting", "License saved. Restart the application to apply it", "License removed. Restart the application to apply it",
            "Operation failed: {0}", "Licensing is unavailable",
        ),
        "zh_TW": (
            "授權", "目前權限：{0}", "免費版", "付費版", "授權狀態：{0}",
            "未啟用", "授權有效", "授權已過期", "授權尚未生效", "授權碼無效", "尚未設定授權驗證公鑰",
            "開發模式：{0}", "全部功能", "模擬免費", "模擬有效", "模擬過期",
            "授權使用者：{0}", "到期時間：{0}", "授權碼", "請輸入授權碼", "啟用", "移除授權",
            "授權變更將在重新啟動後生效", "授權已儲存，請重新啟動應用程式後生效", "授權已移除，請重新啟動應用程式後生效",
            "操作失敗：{0}", "授權不可用",
        ),
        "ja": (
            "ライセンス", "現在の権限：{0}", "無料版", "有料版", "ライセンス状態：{0}",
            "未認証", "有効", "期限切れ", "有効期間前", "無効なライセンスコード", "ライセンス検証用公開鍵が未設定です",
            "開発モード：{0}", "全機能", "無料版の模擬", "有効な認証の模擬", "期限切れの模擬",
            "ライセンス所有者：{0}", "有効期限：{0}", "ライセンスコード", "ライセンスコードを入力", "認証", "ライセンスを削除",
            "ライセンス変更は再起動後に反映されます", "保存しました。アプリを再起動してください", "削除しました。アプリを再起動してください",
            "操作に失敗しました：{0}", "ライセンス機能を利用できません",
        ),
        "ko": (
            "라이선스", "현재 권한: {0}", "무료 버전", "유료 버전", "라이선스 상태: {0}",
            "미인증", "유효", "만료됨", "아직 유효하지 않음", "잘못된 라이선스 코드", "라이선스 검증 공개 키가 설정되지 않았습니다",
            "개발 모드: {0}", "모든 기능", "무료 모의", "유효 모의", "만료 모의",
            "라이선스 사용자: {0}", "만료 시간: {0}", "라이선스 코드", "라이선스 코드를 입력하세요", "활성화", "라이선스 제거",
            "라이선스 변경은 재시작 후 적용됩니다", "저장했습니다. 앱을 재시작하세요", "제거했습니다. 앱을 재시작하세요",
            "작업 실패: {0}", "라이선스를 사용할 수 없습니다",
        ),
        "es": (
            "Licencia", "Acceso actual: {0}", "Gratis", "De pago", "Estado de licencia: {0}",
            "Sin activar", "Válida", "Caducada", "Aún no válida", "Código de licencia no válido", "La clave pública de verificación no está configurada",
            "Modo de desarrollo: {0}", "Todas las funciones", "Gratis simulado", "Válida simulada", "Caducada simulada",
            "Titular: {0}", "Caduca: {0}", "Código de licencia", "Introduce tu código de licencia", "Activar", "Quitar licencia",
            "Los cambios se aplican al reiniciar", "Licencia guardada. Reinicia la aplicación", "Licencia eliminada. Reinicia la aplicación",
            "Error en la operación: {0}", "La licencia no está disponible",
        ),
    }
    for language, values in translations.items():
        register_messages(language, dict(zip(sources, values, strict=True)))
