import uuid
import pytest
from io import BytesIO

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.resource import Resource
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int = 999, school_id: int | None = None):
    def _fake_user():
        return CurrentUser(
            id=user_id,
            sub=str(uuid.uuid4()),
            email=f"{role}-{user_id}@example.com",
            role=role,
            school_id=school_id,
        )

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _make_user(db_session, role_row, prefix, school):
    email = f"{prefix}-{uuid.uuid4()}@example.com"
    user = User(
        supabase_id=uuid.uuid4(),
        email=email,
        full_name=prefix.capitalize(),
        role_id=role_row.id,
        school_id=school.id,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def seed(db_session):
    for r_name in ("admin", "principal", "teacher", "student", "parent"):
        if not db_session.query(Role).filter(Role.name == r_name).first():
            db_session.add(Role(name=r_name))
    db_session.flush()

    school = School(name="Resources Test School")
    db_session.add(school)
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    teacher = _make_user(db_session, teacher_role, "teacher1", school)
    other_teacher = _make_user(db_session, teacher_role, "teacher2", school)

    student_enrolled = _make_user(db_session, student_role, "student_enrolled", school)
    student_not_enrolled = _make_user(db_session, student_role, "student_not_enrolled", school)

    school_class = SchoolClass(
        name="Grade 10 - A",
        academic_year=ACADEMIC_YEAR,
        school_id=school.id,
        class_teacher_id=teacher.id,
        grade_level=10,
    )
    other_class = SchoolClass(
        name="Grade 11 - B",
        academic_year=ACADEMIC_YEAR,
        school_id=school.id,
        class_teacher_id=other_teacher.id,
        grade_level=11,
    )
    db_session.add_all([school_class, other_class])
    db_session.flush()

    physics_subj = Subject(name="Physics", school_id=school.id)
    chemistry_subj = Subject(name="Chemistry", school_id=school.id)
    db_session.add_all([physics_subj, chemistry_subj])
    db_session.flush()

    # Enroll student
    db_session.add(
        Enrollment(
            student_id=student_enrolled.id,
            class_id=school_class.id,
            is_primary=True,
        )
    )
    db_session.flush()

    return {
        "school": school,
        "admin": admin_user,
        "teacher": teacher,
        "other_teacher": other_teacher,
        "student_enrolled": student_enrolled,
        "student_not_enrolled": student_not_enrolled,
        "class": school_class,
        "other_class": other_class,
        "physics": physics_subj,
        "chemistry": chemistry_subj,
    }


def test_teacher_uploads_resource_pdf_and_doc(client, seed):
    """Teacher uploads academic materials organized by subject and unit."""
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    file_content = b"# Optics and Light Waves\n\nChapter summary and practice problems."
    files = {"file": ("optics_summary.md", BytesIO(file_content), "text/markdown")}
    data = {
        "title": "Unit 3: Wave Optics Notes",
        "description": "Comprehensive summary of wave optics and Huygens principle.",
        "unit": "Unit 3: Optics",
        "class_id": str(seed["class"].id),
        "subject_id": str(seed["physics"].id),
    }

    res = client.post("/resources/upload", data=data, files=files)
    assert res.status_code == 201
    payload = res.json()
    assert payload["title"] == "Unit 3: Wave Optics Notes"
    assert payload["unit"] == "Unit 3: Optics"
    assert payload["subject_name"] == "Physics"
    assert payload["class_name"] == "Grade 10 - A"
    assert payload["file_size"] == len(file_content)
    assert payload["teacher_id"] == seed["teacher"].id


def test_teacher_uploads_image_resource(client, seed):
    """Teacher uploads a diagram/image resource."""
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    image_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR..."
    files = {"file": ("ray_diagram.png", BytesIO(image_content), "image/png")}
    data = {
        "title": "Ray Optics Diagram",
        "unit": "Unit 3: Optics",
        "class_id": str(seed["class"].id),
        "subject_id": str(seed["physics"].id),
    }

    res = client.post("/resources/upload", data=data, files=files)
    assert res.status_code == 201
    payload = res.json()
    assert payload["title"] == "Ray Optics Diagram"
    assert "image/png" in payload["mime_type"]


def test_unauthorized_teacher_cannot_upload(client, seed):
    """Teacher not assigned to the class cannot upload to it."""
    _override_user("teacher", user_id=seed["other_teacher"].id, school_id=seed["school"].id)

    files = {"file": ("unauthorized.txt", BytesIO(b"content"), "text/plain")}
    data = {
        "title": "Unauthorized Notes",
        "class_id": str(seed["class"].id),
    }

    res = client.post("/resources/upload", data=data, files=files)
    assert res.status_code == 403


def test_enrolled_student_can_list_class_resources(client, seed, db_session):
    """Enrolled student can view and search resources for their class."""
    resource = Resource(
        school_id=seed["school"].id,
        grade_level=seed["class"].grade_level,
        class_id=seed["class"].id,
        subject_id=seed["physics"].id,
        title="Electromagnetism Worksheet",
        description="Solve questions 1-10 for homework.",
        unit="Unit 4: Electromagnetism",
        file_url="https://example.com/em.pdf",
        mime_type="application/pdf",
        file_size=204800,
        uploaded_by=seed["teacher"].id,
    )
    db_session.add(resource)
    db_session.flush()

    _override_user("student", user_id=seed["student_enrolled"].id, school_id=seed["school"].id)

    res = client.get(f"/resources/{seed['class'].id}")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) >= 1
    assert data["items"][0]["title"] == "Electromagnetism Worksheet"
    assert data["items"][0]["unit"] == "Unit 4: Electromagnetism"


def test_non_enrolled_student_cannot_list_class_resources(client, seed):
    """Non-enrolled student receives 403 Forbidden."""
    _override_user("student", user_id=seed["student_not_enrolled"].id, school_id=seed["school"].id)

    res = client.get(f"/resources/{seed['class'].id}")
    assert res.status_code == 403


def test_resource_search_and_filters(client, seed, db_session):
    """Search query and filters (subject, unit) correctly filter resources."""
    r1 = Resource(
        school_id=seed["school"].id,
        grade_level=seed["class"].grade_level,
        class_id=seed["class"].id,
        subject_id=seed["physics"].id,
        title="Thermodynamics Formula Sheet",
        description="Heat engine and Carnot cycle laws.",
        unit="Unit 1: Thermodynamics",
        file_url="https://example.com/thermo.pdf",
        mime_type="application/pdf",
        uploaded_by=seed["teacher"].id,
    )
    r2 = Resource(
        school_id=seed["school"].id,
        grade_level=seed["class"].grade_level,
        class_id=seed["class"].id,
        subject_id=seed["chemistry"].id,
        title="Organic Chemistry Reactions",
        description="Alkanes and polymers roadmap.",
        unit="Unit 2: Organic Chemistry",
        file_url="https://example.com/organic.pdf",
        mime_type="application/pdf",
        uploaded_by=seed["teacher"].id,
    )
    db_session.add_all([r1, r2])
    db_session.flush()

    _override_user("student", user_id=seed["student_enrolled"].id, school_id=seed["school"].id)

    # Search by text query
    res_search = client.get(f"/resources/{seed['class'].id}?q=Carnot")
    assert res_search.status_code == 200
    items = res_search.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Thermodynamics Formula Sheet"

    # Filter by unit
    res_unit = client.get(f"/resources/{seed['class'].id}?unit=Unit 2: Organic Chemistry")
    assert res_unit.status_code == 200
    items_unit = res_unit.json()["items"]
    assert len(items_unit) == 1
    assert items_unit[0]["title"] == "Organic Chemistry Reactions"

    # Filter by subject
    res_subj = client.get(f"/resources/{seed['class'].id}?subject_id={seed['physics'].id}")
    assert res_subj.status_code == 200
    items_subj = res_subj.json()["items"]
    assert all(i["subject_id"] == seed["physics"].id for i in items_subj)


def test_distinct_units_endpoint(client, seed, db_session):
    """GET /resources/units returns distinct unit list."""
    r1 = Resource(
        school_id=seed["school"].id,
        grade_level=seed["class"].grade_level,
        class_id=seed["class"].id,
        subject_id=seed["physics"].id,
        title="Kinematics",
        unit="Unit 1: Motion",
        file_url="https://example.com/kinematics.pdf",
        mime_type="application/pdf",
        uploaded_by=seed["teacher"].id,
    )
    r2 = Resource(
        school_id=seed["school"].id,
        grade_level=seed["class"].grade_level,
        class_id=seed["class"].id,
        subject_id=seed["physics"].id,
        title="Dynamics",
        unit="Unit 2: Forces",
        file_url="https://example.com/dynamics.pdf",
        mime_type="application/pdf",
        uploaded_by=seed["teacher"].id,
    )
    db_session.add_all([r1, r2])
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    res = client.get(f"/resources/units?class_id={seed['class'].id}")
    assert res.status_code == 200
    data = res.json()
    assert "Unit 1: Motion" in data["units"]
    assert "Unit 2: Forces" in data["units"]


def test_teacher_deletes_own_resource(client, seed, db_session):
    """Author teacher can delete their resource; other teacher cannot."""
    resource = Resource(
        school_id=seed["school"].id,
        grade_level=seed["class"].grade_level,
        class_id=seed["class"].id,
        subject_id=seed["physics"].id,
        title="To be deleted",
        file_url="https://example.com/delete.pdf",
        mime_type="application/pdf",
        uploaded_by=seed["teacher"].id,
    )
    db_session.add(resource)
    db_session.flush()

    # Other teacher tries to delete
    _override_user("teacher", user_id=seed["other_teacher"].id, school_id=seed["school"].id)
    res_unauth = client.delete(f"/resources/{resource.id}")
    assert res_unauth.status_code == 403

    # Author deletes
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)
    res_auth = client.delete(f"/resources/{resource.id}")
    assert res_auth.status_code == 204

    # Verify deleted from DB
    deleted = db_session.query(Resource).filter(Resource.id == resource.id).first()
    assert deleted is None
