"""
邮件转发助手 - 后端服务
Flask REST API + SQLite
"""
import os
import json
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# 数据库配置
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_forwarder.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB，邮件可能含大量base64图片

db = SQLAlchemy(app)


# ==================== 数据模型 ====================

class ReceivedEmail(db.Model):
    __tablename__ = "received_emails"
    __table_args__ = (
        db.Index("ix_email_employee", "email_id", "employee_id"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email_id = db.Column(db.String(500), nullable=False)
    subject = db.Column(db.Text, default="")
    sender_email = db.Column(db.String(500), default="")
    sender_name = db.Column(db.String(500), default="")
    received_time = db.Column(db.DateTime)
    html_body = db.Column(db.Text, default="")
    text_body = db.Column(db.Text, default="")
    matched_rule_name = db.Column(db.String(200), default="")
    # 用户信息
    employee_id = db.Column(db.String(100), default="")
    department = db.Column(db.String(200), default="")
    product_category = db.Column(db.String(200), default="")
    custom_json_config = db.Column(db.Text, default="{}")
    # 内嵌图片JSON
    embedded_images_json = db.Column(db.Text, default="[]")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ErrorLog(db.Model):
    __tablename__ = "error_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    error_message = db.Column(db.Text, default="")
    stack_trace = db.Column(db.Text)
    occurred_at = db.Column(db.DateTime)
    email_id = db.Column(db.String(500))
    employee_id = db.Column(db.String(100))
    department = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


# ==================== API 接口 ====================

@app.route("/api/email/ping", methods=["GET"])
def ping():
    """健康检查 / 连通性测试"""
    return jsonify({"Success": True, "Message": "pong"})


@app.route("/api/email/receive", methods=["POST"])
def receive_email():
    """接收邮件数据"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"Success": False, "Message": "Invalid JSON"}), 400

    email_id = data.get("EmailId", "")
    if not email_id:
        return jsonify({"Success": False, "Message": "EmailId is required"}), 400

    extra_info = data.get("ExtraInfo") or {}
    employee_id = extra_info.get("EmployeeId", "")

    # 去重：同一用户 + 同一封邮件 不重复入库（不同用户上传同一封邮件都保留）
    exists = ReceivedEmail.query.filter_by(
        email_id=email_id, employee_id=employee_id
    ).first()
    if exists:
        return jsonify({"Success": True, "Message": "Already received, skipped"})

    record = ReceivedEmail(
        email_id=email_id,
        subject=data.get("Subject", ""),
        sender_email=data.get("SenderEmail", ""),
        sender_name=data.get("SenderName", ""),
        received_time=_parse_time(data.get("ReceivedTime")),
        html_body=data.get("HtmlBody", ""),
        text_body=data.get("TextBody", ""),
        matched_rule_name=data.get("MatchedRuleName", ""),
        employee_id=extra_info.get("EmployeeId", ""),
        department=extra_info.get("Department", ""),
        product_category=extra_info.get("ProductCategory", ""),
        custom_json_config=data.get("CustomJsonConfig", "{}"),
        embedded_images_json=json.dumps(data.get("EmbeddedImages", [])),
    )
    db.session.add(record)
    db.session.commit()

    app.logger.info(
        "Received email: %s from %s (Rule: %s, Employee: %s)",
        record.subject, record.sender_email,
        record.matched_rule_name, record.employee_id,
    )
    return jsonify({"Success": True, "Message": "Received successfully"})


@app.route("/api/email/error", methods=["POST"])
def report_error():
    """接收错误上报"""
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
        department=extra_info.get("Department"),
    )
    db.session.add(record)
    db.session.commit()

    app.logger.warning(
        "Error reported from %s: %s", record.employee_id, record.error_message
    )
    return jsonify({"Success": True, "Message": "Error logged"})


@app.route("/api/email/list", methods=["GET"])
def list_emails():
    """查询已接收的邮件（管理用），支持按部门/工号/产品分类过滤"""
    department = request.args.get("department")
    employee_id = request.args.get("employeeId")
    product_category = request.args.get("productCategory")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("pageSize", 20))

    query = ReceivedEmail.query

    if department:
        query = query.filter_by(department=department)
    if employee_id:
        query = query.filter_by(employee_id=employee_id)
    if product_category:
        query = query.filter_by(product_category=product_category)

    total = query.count()
    items = (
        query.order_by(ReceivedEmail.created_at.desc())
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
                "EmailId": e.email_id,
                "Subject": e.subject,
                "SenderEmail": e.sender_email,
                "SenderName": e.sender_name,
                "ReceivedTime": e.received_time.isoformat() if e.received_time else None,
                "MatchedRuleName": e.matched_rule_name,
                "EmployeeId": e.employee_id,
                "Department": e.department,
                "ProductCategory": e.product_category,
                "CreatedAt": e.created_at.isoformat() if e.created_at else None,
            }
            for e in items
        ],
    })


@app.route("/api/email/<int:email_id>", methods=["GET"])
def get_email_detail(email_id):
    """查看邮件详情（含HTML正文）"""
    record = ReceivedEmail.query.get(email_id)
    if not record:
        return jsonify({"Success": False, "Message": "Not found"}), 404

    return jsonify({
        "Id": record.id,
        "EmailId": record.email_id,
        "Subject": record.subject,
        "SenderEmail": record.sender_email,
        "SenderName": record.sender_name,
        "ReceivedTime": record.received_time.isoformat() if record.received_time else None,
        "HtmlBody": record.html_body,
        "TextBody": record.text_body,
        "MatchedRuleName": record.matched_rule_name,
        "EmployeeId": record.employee_id,
        "Department": record.department,
        "ProductCategory": record.product_category,
        "CustomJsonConfig": record.custom_json_config,
        "EmbeddedImagesJson": record.embedded_images_json,
        "CreatedAt": record.created_at.isoformat() if record.created_at else None,
    })


@app.route("/api/email/errors", methods=["GET"])
def list_errors():
    """查询错误日志"""
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("pageSize", 20))

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
                "Department": e.department,
                "CreatedAt": e.created_at.isoformat() if e.created_at else None,
            }
            for e in items
        ],
    })


# ==================== 工具函数 ====================

def _parse_time(value):
    """兼容C#发过来的各种时间格式"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
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
    # 带时区偏移的格式（如 2026-04-16T10:30:00+08:00）
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


# ==================== 启动 ====================

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
