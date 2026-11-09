"""Shared definitions for Git workflow forms and summaries."""

STEP_LABELS = {
    "MERGE_BRANCH": "更新、合并并推送",
    "COMMIT_PUSH": "更新、提交并推送",
    "PULL": "拉取代码",
    "MAVEN_BUILD": "Maven 打包",
}
FIELD_LABELS = {
    "SOURCE_PROJECT_PATH": "源目录", "SOURCE_BRANCH": "源分支名称",
    "TARGET_PROJECT_PATH": "目标目录", "TARGET_BRANCH": "目标分支名称",
    "PROJECT_PATH": "项目目录", "COMMIT_MESSAGE": "提交说明",
    "CONFLICT_POLICY": "冲突处理",
    "ARTIFACT_NAME": "产物名称", "JAR_FILTER": "JAR 筛选",
    "BUILD_TIMEOUT": "打包超时（秒）",
}
STEP_FIELDS = {
    "MERGE_BRANCH": ("SOURCE_PROJECT_PATH", "SOURCE_BRANCH", "TARGET_PROJECT_PATH", "TARGET_BRANCH"),
    "COMMIT_PUSH": ("PROJECT_PATH", "COMMIT_MESSAGE"),
    "PULL": ("PROJECT_PATH",),
    "MAVEN_BUILD": ("PROJECT_PATH", "ARTIFACT_NAME", "JAR_FILTER", "BUILD_TIMEOUT"),
}
STEP_HINTS = {
    "MERGE_BRANCH": "更新目标分支，合并源分支后推送；原项目不变。",
    "COMMIT_PUSH": "更新当前分支，提交已暂存改动并推送；未暂存改动不提交。",
    "PULL": "更新当前分支；默认分叉时停止，选择手动合并后可处理分叉。",
    "MAVEN_BUILD": "执行 Maven clean package；优先使用项目 Maven Wrapper，失败时停止后续流程。",
}
POLICIES = {"rollback": "回退", "merge": "手动合并"}
