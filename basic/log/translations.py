"""Log viewer interface text; stored output remains unchanged."""

MESSAGES = {
    "en": {"日志": "Logs", "刷新": "Refresh", "仅预览最后 4 MB，日志文件完整保留": "Preview shows the last 4 MB; the complete log file is retained", "确定删除日志“{0}”吗？": "Delete log \"{0}\"?"},
    "zh_TW": {"日志": "日誌", "刷新": "重新整理", "仅预览最后 4 MB，日志文件完整保留": "僅預覽最後 4 MB，日誌檔完整保留", "确定删除日志“{0}”吗？": "確定刪除日誌「{0}」嗎？"},
    "ja": {"日志": "ログ", "刷新": "更新", "仅预览最后 4 MB，日志文件完整保留": "末尾 4 MB のプレビューです。ログ全体は保存されています", "确定删除日志“{0}”吗？": "ログ「{0}」を削除しますか？"},
    "ko": {"日志": "로그", "刷新": "새로 고침", "仅预览最后 4 MB，日志文件完整保留": "마지막 4 MB만 표시하며 전체 로그 파일은 보존됩니다", "确定删除日志“{0}”吗？": "로그 \"{0}\"을 삭제할까요?"},
    "es": {"日志": "Registros", "刷新": "Actualizar", "仅预览最后 4 MB，日志文件完整保留": "La vista previa muestra los últimos 4 MB; se conserva el registro completo", "确定删除日志“{0}”吗？": "¿Eliminar el registro «{0}»?"},
}

for language, hide, show in (
    ("en", "Hide timestamps", "Show timestamps"),
    ("zh_TW", "隱藏時間", "顯示時間"),
    ("ja", "時刻を非表示", "時刻を表示"),
    ("ko", "시간 숨기기", "시간 표시"),
    ("es", "Ocultar marcas de tiempo", "Mostrar marcas de tiempo"),
):
    MESSAGES[language]["隐藏时间"] = hide
    MESSAGES[language]["显示时间"] = show

for language, title in (
    ("en", "Session log: {0}"), ("zh_TW", "工作階段日誌：{0}"),
    ("ja", "セッションログ：{0}"), ("ko", "세션 로그: {0}"), ("es", "Registro de sesión: {0}"),
):
    MESSAGES[language]["会话日志：{0}"] = title

for language, message in (
    ("en", "Log writing failed: {0}"), ("zh_TW", "日誌寫入失敗：{0}"),
    ("ja", "ログの書き込みに失敗しました：{0}"), ("ko", "로그 기록 실패: {0}"),
    ("es", "No se pudo escribir el registro: {0}"),
):
    MESSAGES[language]["日志写入失败：{0}"] = message

for language, label, error in (
    ("en", "Logs (error)", "Configuration log writing failed: {0}"),
    ("zh_TW", "日誌（異常）", "設定日誌寫入失敗：{0}"),
    ("ja", "ログ（エラー）", "設定ログの書き込みに失敗しました：{0}"),
    ("ko", "로그 (오류)", "구성 로그 기록 실패: {0}"),
    ("es", "Registros (error)", "No se pudo escribir el registro de configuración: {0}"),
):
    MESSAGES[language]["日志（异常）"] = label
    MESSAGES[language]["配置日志写入失败：{0}"] = error

for language, placeholder, shortcut, no_match in (
    ("en", "Find in log", "Find in log (Ctrl+F)", "No matches"),
    ("zh_TW", "尋找日誌內容", "尋找日誌內容（Ctrl+F）", "沒有符合項目"),
    ("ja", "ログ内を検索", "ログ内を検索（Ctrl+F）", "一致する項目がありません"),
    ("ko", "로그에서 찾기", "로그에서 찾기 (Ctrl+F)", "일치하는 결과 없음"),
    ("es", "Buscar en el registro", "Buscar en el registro (Ctrl+F)", "Sin coincidencias"),
):
    MESSAGES[language].update({"查找日志内容": placeholder, "查找日志内容（Ctrl+F）": shortcut, "未找到匹配": no_match})
