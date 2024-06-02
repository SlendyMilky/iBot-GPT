# modules/utils.py
def split_text(text, max_length=4096):
    words = text.split()
    parts = []
    current_part = words[0]

    for word in words[1:]:
        if len(current_part) + len(word) + 1 <= max_length:
            current_part += " " + word
        else:
            parts.append(current_part)
            current_part = word

    parts.append(current_part)
    return parts
