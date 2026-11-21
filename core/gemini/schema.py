TRANSCRIBE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "pages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "image_index": {"type": "INTEGER"},
                    "page_no": {"type": "INTEGER"},
                    "paragraphs": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "text": {"type": "STRING"},
                                "is_bold": {"type": "BOOLEAN"},
                                "is_heading": {"type": "BOOLEAN"},
                                "heading_level": {"type": "INTEGER"},
                                "block_type": {"type": "STRING"},
                                "reading_order": {"type": "INTEGER"},
                                "is_toc_entry": {"type": "BOOLEAN"},
                                "is_scene_break": {"type": "BOOLEAN"},
                            },
                            "required": ["text", "is_bold", "is_heading", "is_scene_break", "heading_level", "block_type", "reading_order", "is_toc_entry"],
                        },
                    },
                    "ends_open": {"type": "BOOLEAN"},
                },
                "required": ["image_index", "page_no", "paragraphs", "ends_open"],
            },
        }
    },
    "required": ["pages"],
}
