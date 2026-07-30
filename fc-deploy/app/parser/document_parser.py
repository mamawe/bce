from __future__ import annotations
"""
文档解析器 - 将 Markdown 周报拆分为结构化块
"""
import re
from dataclasses import dataclass, field


@dataclass
class DocumentMetadata:
    title: str = ""
    date: str = ""
    author: str = ""
    period: str = ""


@dataclass
class Section:
    heading: str
    content: str
    level: int = 2


@dataclass
class ParsedDocument:
    metadata: DocumentMetadata
    sections: list[Section] = field(default_factory=list)
    raw_text: str = ""


def parse_markdown(text: str) -> ParsedDocument:
    """
    解析 Markdown 周报：
    1. 提取元数据（标题、日期、报告人）
    2. 按 ## 标题拆分为 sections
    """
    lines = text.split("\n")
    metadata = DocumentMetadata()

    # 提取一级标题作为文档标题
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            metadata.title = line[2:].strip()
            break

    # 提取元数据字段
    for line in lines:
        if "**报告人**" in line:
            metadata.author = re.sub(r"\*{0,2}报告人\*{0,2}[：:]\s*", "", line).strip()
        elif "**日期**" in line:
            metadata.date = re.sub(r"\*{0,2}日期\*{0,2}[：:]\s*", "", line).strip()
        elif "**覆盖周期**" in line:
            metadata.period = re.sub(r"\*{0,2}覆盖周期\*{0,2}[：:]\s*", "", line).strip()

    # 按 ## 拆分 sections
    sections: list[Section] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in lines:
        # 匹配 ## 或 ### 标题
        heading_match = re.match(r"^(#{2,3})\s+(.+)", line)
        if heading_match:
            # 保存上一个 section
            if current_heading:
                sections.append(Section(
                    heading=current_heading,
                    content="\n".join(current_lines).strip(),
                ))
            current_heading = heading_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # 最后一个 section
    if current_heading:
        sections.append(Section(
            heading=current_heading,
            content="\n".join(current_lines).strip(),
        ))

    return ParsedDocument(
        metadata=metadata,
        sections=sections,
        raw_text=text,
    )


def build_extraction_context(parsed: ParsedDocument) -> str:
    """
    将解析后的文档组装为发送给 LLM 的上下文文本
    保留结构但去除无关格式噪音
    """
    parts = [f"文档标题: {parsed.metadata.title}"]
    if parsed.metadata.date:
        parts.append(f"日期: {parsed.metadata.date}")
    if parsed.metadata.period:
        parts.append(f"覆盖周期: {parsed.metadata.period}")
    parts.append("")

    for section in parsed.sections:
        parts.append(f"## {section.heading}")
        parts.append(section.content)
        parts.append("")

    return "\n".join(parts)
