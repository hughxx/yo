from server.db.models.email import Collection


def get_or_create_collection(db, name: str):
    """按名称查找 Collection，不存在则自动创建。"""
    col = db.query(Collection).filter_by(name=name).first()
    if col is None:
        col = Collection(name=name, description="")
        db.add(col)
        db.flush()
    return col
