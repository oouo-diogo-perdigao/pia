def clean_text(text):
    """
    Limpa o texto removendo caracteres indesejados e formatando Markdown.
    """
    import re

    # Remove caracteres nulos
    text = text.replace("\x00", " ")
    # Normaliza quebras de linha
    text = re.sub(r"\r\n?", "\n", text)
    # Remove links Markdown, mantendo apenas o texto visível.
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove blocos de código Markdown.
    text = re.sub(r"```(?:\w+)?\s*([\s\S]*?)```", r"\1", text)
    # Remove código inline.
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove negrito e itálico Markdown.
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?<!\w)\*(.*?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_(.*?)_(?!\w)", r"\1", text)
    # Remove cabeçalhos Markdown.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    # Remove citações Markdown.
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    # Remove marcadores de listas.
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    # Remove marcadores de checkbox.
    text = re.sub(r"(?m)^\s*\[[ xX]\]\s*", "", text)
    # Remove linhas horizontais Markdown.
    text = re.sub(r"(?m)^\s*([-*_])(?:\s*\1){2,}\s*$", "", text)
    # Remove espaços repetidos.
    text = re.sub(r"[ \t]+", " ", text)
    # Reduz excesso de linhas vazias.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
