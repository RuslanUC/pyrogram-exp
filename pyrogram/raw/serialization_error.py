class DeserializationError(Exception):
    def __init__(self, parent_object_name: str, field_name: str, field_type: str, got_id: int):
        super().__init__(
            f"Failed to deserialize {parent_object_name} object's field {field_name}. "
            f"Expected {field_type} type, got type with constructor {got_id}."
        )
