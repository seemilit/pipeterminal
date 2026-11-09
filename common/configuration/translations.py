"""Configuration protection errors available before feature modules load."""

from common.i18n import register_messages


ROWS = (
    ("无法读取稳定的机器标识，配置未保存", "Cannot read a stable machine ID; configuration was not saved", "無法讀取穩定的機器識別碼，設定未儲存", "安定したマシン ID を取得できないため、設定は保存されませんでした", "안정적인 머신 ID를 읽을 수 없어 설정을 저장하지 않았습니다", "No se pudo leer un identificador estable del equipo; no se guardó la configuración"),
    ("配置加密失败，原文件未修改", "Configuration encryption failed; the original file was not changed", "設定加密失敗，原始檔案未修改", "設定の暗号化に失敗しました。元のファイルは変更されていません", "설정 암호화에 실패했습니다. 원본 파일은 변경되지 않았습니다", "Falló el cifrado de la configuración; el archivo original no se modificó"),
    ("配置无法解密：不是原电脑，或文件已损坏", "Cannot decrypt configuration: a different computer or a damaged file", "無法解密設定：不是原電腦，或檔案已損壞", "設定を復号できません。別のコンピューターか、ファイルが破損しています", "설정을 복호화할 수 없습니다. 다른 컴퓨터이거나 파일이 손상되었습니다", "No se puede descifrar la configuración: es otro equipo o el archivo está dañado"),
    ("配置加载失败", "Could not load configuration", "設定載入失敗", "設定を読み込めません", "설정 불러오기 실패", "No se pudo cargar la configuración"),
)


def register_translations():
    for index, language in enumerate(("en", "zh_TW", "ja", "ko", "es"), 1):
        register_messages(language, {row[0]: row[index] for row in ROWS})
