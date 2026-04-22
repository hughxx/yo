"""
邮件转发助手 - 后端服务
Flask REST API + SQLite
"""
import os
import re
import json
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_forwarder.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

db = SQLAlchemy(app)


# ==================== 数据模型 ====================

class Email(db.Model):
    """
    邮件主体表，以 conversation_topic 为业务唯一键。
    同一话题多次上传时，保留 received_time 最新的那封内容。
    """
    __tablename__ = "emails"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    conversation_topic = db.Column(db.String(500), nullable=False, unique=True, index=True)
    subject = db.Column(db.Text, default="")
    sender_email = db.Column(db.String(500), default="")
    sender_name = db.Column(db.String(500), default="")
    received_time = db.Column(db.DateTime)
    html_body = db.Column(db.Text, default="")
    text_body = db.Column(db.Text, default="")
    embedded_images_json = db.Column(db.Text, default="[]")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    employees = db.relationship("EmailEmployee", backref="email", lazy="dynamic",
                                cascade="all, delete-orphan")
    products = db.relationship("EmailProduct", backref="email", lazy="dynamic",
                               cascade="all, delete-orphan")


class EmailEmployee(db.Model):
    """邮件 ↔ 上传员工  多对多关联"""
    __tablename__ = "email_employees"
    __table_args__ = (
        db.UniqueConstraint("email_id", "employee_id", name="uq_email_employee"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email_id = db.Column(db.Integer, db.ForeignKey("emails.id"), nullable=False, index=True)
    employee_id = db.Column(db.String(100), nullable=False, index=True)
    matched_rule_name = db.Column(db.String(200), default="")
    custom_json_config = db.Column(db.Text, default="{}")
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class EmailProduct(db.Model):
    """邮件 ↔ 产品  多对多关联"""
    __tablename__ = "email_products"
    __table_args__ = (
        db.UniqueConstraint("email_id", "product_name", name="uq_email_product"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email_id = db.Column(db.Integer, db.ForeignKey("emails.id"), nullable=False, index=True)
    product_name = db.Column(db.String(200), nullable=False)


class ErrorLog(db.Model):
    __tablename__ = "error_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    error_message = db.Column(db.Text, default="")
    stack_trace = db.Column(db.Text)
    occurred_at = db.Column(db.DateTime)
    email_id = db.Column(db.String(500))
    employee_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


# ==================== API 接口 ====================

@app.route("/api/email/ping", methods=["GET"])
def ping():
    return jsonify({"Success": True, "Message": "pong"})


@app.route("/api/email/receive", methods=["POST"])
def receive_email():
    """
    接收邮件数据。
    以 conversation_topic 为唯一键：
      - 新话题 → 插入 Email
      - 已有话题但新的 received_time 更新 → 用最新内容覆盖 Email
    员工和产品通过关联表写入（已存在则跳过）。
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"Success": False, "Message": "Invalid JSON"}), 400

    conversation_topic = (data.get("ConversationTopic") or "").strip()
    if not conversation_topic:
        return jsonify({"Success": False, "Message": "ConversationTopic is required"}), 400

    extra_info = data.get("ExtraInfo") or {}
    employee_id = (extra_info.get("EmployeeId") or "").strip()
    product_category = (extra_info.get("ProductCategory") or "").strip()

    received_time = _parse_time(data.get("ReceivedTime"))

    # 1. 查找或新建 Email（以 conversation_topic 去重，保留最新内容）
    email = Email.query.filter_by(conversation_topic=conversation_topic).first()
    if email is None:
        email = Email(
            conversation_topic=conversation_topic,
            subject=data.get("Subject", ""),
            sender_email=data.get("SenderEmail", ""),
            sender_name=data.get("SenderName", ""),
            received_time=received_time,
            html_body=data.get("HtmlBody", ""),
            text_body=data.get("TextBody", ""),
            embedded_images_json=json.dumps(data.get("EmbeddedImages", [])),
        )
        db.session.add(email)
        db.session.flush()  # 拿到 email.id
    elif received_time and (email.received_time is None or received_time > email.received_time):
        # 用更新的邮件内容替换
        email.subject = data.get("Subject", "")
        email.sender_email = data.get("SenderEmail", "")
        email.sender_name = data.get("SenderName", "")
        email.received_time = received_time
        email.html_body = data.get("HtmlBody", "")
        email.text_body = data.get("TextBody", "")
        email.embedded_images_json = json.dumps(data.get("EmbeddedImages", []))
        email.updated_at = datetime.now(timezone.utc)

    # 2. 关联员工（同一员工重复上传同一话题 → 忽略）
    if employee_id:
        exists = EmailEmployee.query.filter_by(
            email_id=email.id, employee_id=employee_id
        ).first()
        if not exists:
            db.session.add(EmailEmployee(
                email_id=email.id,
                employee_id=employee_id,
                matched_rule_name=data.get("MatchedRuleName", ""),
                custom_json_config=data.get("CustomJsonConfig", "{}"),
            ))

    # 3. 关联产品（同一产品重复关联 → 忽略）
    if product_category:
        exists = EmailProduct.query.filter_by(
            email_id=email.id, product_name=product_category
        ).first()
        if not exists:
            db.session.add(EmailProduct(
                email_id=email.id,
                product_name=product_category,
            ))

    db.session.commit()

    app.logger.info(
        "Email upserted: topic=%s subject=%s employee=%s product=%s",
        conversation_topic, data.get("Subject", ""), employee_id, product_category,
    )
    return jsonify({"Success": True, "Message": "Received successfully"})


@app.route("/api/email/error", methods=["POST"])
def report_error():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"Success": False, "Message": "Invalid JSON"}), 400

    extra_info = data.get("ExtraInfo") or {}
    record = ErrorLog(
        error_message=data.get("ErrorMessage", ""),
        stack_trace=data.get("StackTrace"),
        occurred_at=_parse_time(data.get("OccurredAt")),
        email_id=data.get("EmailId"),
        employee_id=extra_info.get("EmployeeId"),
    )
    db.session.add(record)
    db.session.commit()
    return jsonify({"Success": True, "Message": "Error logged"})


@app.route("/api/email/list", methods=["GET"])
def list_emails():
    """查询邮件列表，支持按产品/工号过滤，返回关联的员工和产品"""
    employee_id = request.args.get("employeeId")
    product_name = request.args.get("productName")
    page = max(1, int(request.args.get("page", 1)))
    page_size = max(1, min(100, int(request.args.get("pageSize", 20))))

    query = Email.query

    if employee_id:
        query = query.join(EmailEmployee).filter(EmailEmployee.employee_id == employee_id)
    if product_name:
        query = query.join(EmailProduct).filter(EmailProduct.product_name == product_name)

    total = query.count()
    items = (
        query.order_by(Email.received_time.desc().nulls_last())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return jsonify({
        "Total": total,
        "Page": page,
        "PageSize": page_size,
        "Items": [_email_summary(e) for e in items],
    })


@app.route("/api/email/<int:email_id>", methods=["GET"])
def get_email_detail(email_id):
    email = db.session.get(Email, email_id)
    if not email:
        return jsonify({"Success": False, "Message": "Not found"}), 404

    return jsonify({
        **_email_summary(email),
        "HtmlBody": email.html_body,
        "TextBody": email.text_body,
        "EmbeddedImagesJson": email.embedded_images_json,
    })


@app.route("/api/email/errors", methods=["GET"])
def list_errors():
    page = max(1, int(request.args.get("page", 1)))
    page_size = max(1, min(100, int(request.args.get("pageSize", 20))))

    total = ErrorLog.query.count()
    items = (
        ErrorLog.query.order_by(ErrorLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return jsonify({
        "Total": total,
        "Page": page,
        "PageSize": page_size,
        "Items": [
            {
                "Id": e.id,
                "ErrorMessage": e.error_message,
                "StackTrace": e.stack_trace,
                "OccurredAt": e.occurred_at.isoformat() if e.occurred_at else None,
                "EmailId": e.email_id,
                "EmployeeId": e.employee_id,
                "CreatedAt": e.created_at.isoformat() if e.created_at else None,
            }
            for e in items
        ],
    })


# ---------- 产品 / 员工查询（stub，按实际系统实现） ----------

@app.route("/api/products", methods=["GET"])
def get_products():
    """
    返回可用产品列表。
    TODO: 替换为从数据库或配置中心读取的实际产品列表。
    """
    products = ["产品A", "产品B", "产品C"]
    return jsonify({"code": 200, "data": products})


@app.route("/api/user/search", methods=["GET"])
def search_user():
    """
    员工模糊查询（按姓名/工号关键词）。
    TODO: 替换为查询企业 AD/LDAP 或员工数据库的实际实现。
    返回格式: {code: 200, data: [{id, name, sAMAccountName}]}
    """
    keyword = (request.args.get("keyword") or "").strip()
    # stub：返回空列表，实际应查询 AD/员工库
    return jsonify({"code": 200, "data": []})


# ==================== 工具函数 ====================

def _email_summary(e: Email) -> dict:
    return {
        "Id": e.id,
        "ConversationTopic": e.conversation_topic,
        "Subject": e.subject,
        "SenderEmail": e.sender_email,
        "SenderName": e.sender_name,
        "ReceivedTime": e.received_time.isoformat() if e.received_time else None,
        "Employees": [
            {
                "EmployeeId": ee.employee_id,
                "MatchedRuleName": ee.matched_rule_name,
                "UploadedAt": ee.uploaded_at.isoformat() if ee.uploaded_at else None,
            }
            for ee in e.employees
        ],
        "Products": [ep.product_name for ep in e.products],
        "CreatedAt": e.created_at.isoformat() if e.created_at else None,
        "UpdatedAt": e.updated_at.isoformat() if e.updated_at else None,
    }


def _parse_time(value):
    """兼容 C# 发过来的各种时间格式，包括 /Date(xxx+xxxx)/ 格式"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value

    # JavaScriptSerializer 格式: /Date(1713600000000+0800)/
    m = re.match(r"/Date\((-?\d+)([+-]\d{4})?\)/", str(value))
    if m:
        ms = int(m.group(1))
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    try:
        dt = datetime.fromisoformat(value)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


# ==================== 启动 ====================

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
