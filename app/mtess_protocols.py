"""Generación y seguimiento documental MTESS 195/2026 y 564/2026.

Se integra en Certificados y reutiliza GeneratedCertificate: no modifica ni
duplica las empresas, los legajos, las liquidaciones ni los cálculos.
Las plantillas son modelos adaptables, NO resoluciones de homologación.
"""
from __future__ import annotations

import io
from datetime import date, datetime, UTC
from urllib.parse import quote

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .document_export import (
    ExportData, build_docx_bytes, build_pdf_bytes, decode_metadata,
    encode_metadata, export_data_from_certificate, safe_download_name,
)
from .models import Company, Employee, GeneratedCertificate

DECLARATION = "mtess_declaracion_tolerancia_cero"
PROTOCOL = "mtess_protocolo_acoso_laboral"
TYPES = (DECLARATION, PROTOCOL)
LABELS = {
    DECLARATION: "Declaración de Tolerancia Cero — Anexo III",
    PROTOCOL: "Protocolo de Prevención, Atención e Investigación — Anexo II",
}
SOURCE_URL = (
    "https://www.mtess.gov.py/wp-content/uploads/2026/03/"
    "Resolucion-MTESS-N%C2%B0-195-Protocolo-de-violencia-laboral.pdf"
)
DEADLINE = date(2026, 12, 31)


def applicable_type(active_count: int) -> str:
    """El umbral legal es 10 trabajadores (10 inclusive)."""
    if active_count < 0:
        raise ValueError("Cantidad de trabajadores inválida")
    return DECLARATION if active_count <= 10 else PROTOCOL


def is_active_employee(employee: Employee) -> bool:
    return (
        (employee.status or "").strip().casefold() in {"activo", "activa"}
        and employee.termination_date is None
    )


def _company_text(company: Company) -> list[str]:
    lines = [f"EMPRESA: {company.legal_name}", f"RUC: {company.ruc}"]
    if company.address:
        lines.append(f"DOMICILIO: {company.address}")
    if company.city:
        lines.append(f"CIUDAD: {company.city}")
    return lines


def build_declaration(company: Company, *, responsible: str, channel: str, hours: str) -> str:
    """Declaración propia basada en el Anexo III; no se presenta como transcripción literal."""
    return "\n\n".join([
        "DECLARACIÓN DE TOLERANCIA CERO FRENTE A LA DISCRIMINACIÓN, "
        "LA VIOLENCIA Y EL ACOSO EN EL ESPACIO DE TRABAJO",
        "\n".join(_company_text(company)),
        f"{company.legal_name} declara su compromiso de mantener un espacio de trabajo "
        "seguro, digno y respetuoso, libre de discriminación, violencia y acoso.",
        "La empresa establece una política de tolerancia cero respecto de toda "
        "conducta de violencia física, psicológica o sexual, hostigamiento, "
        "humillación, amenaza o discriminación, cualquiera sea la posición "
        "jerárquica de las personas involucradas.",
        "Esta política se extiende a empleadores, representantes, trabajadores "
        "y demás personas relacionadas con las actividades laborales, "
        "sin perjuicio del ámbito de aplicación establecido por la normativa.",
        "Se facilitarán canales accesibles para informar y denunciar hechos, "
        "con confidencialidad, imparcialidad, protección de las personas "
        "involucradas, prohibición de represalias y respeto al debido proceso.",
        "Las denuncias se atenderán e investigarán conforme al Capítulo IV "
        "de la Resolución MTESS N.º 195/2026 y sus modificaciones. "
        "Cuando la denuncia sea contra el empleador o sus representantes, "
        "corresponde recurrir directamente al MTESS.",
        f"Responsable de recepción y orientación: {responsible}.\n"
        f"Canal de contacto: {channel}.\nHorario de atención: {hours or 'Horario habitual de la empresa'}.",
        "La presente declaración se comunicará a todo el personal, se adjuntará "
        "a los contratos de trabajo y se exhibirá en un lugar visible.",
        "Fundamento: Resolución MTESS N.º 195/2026, Anexo I, numeral 11.b, "
        "Anexo III, y modificaciones introducidas por la Resolución N.º 564/2026.",
        f"{company.city or 'Paraguay'}, {date.today().strftime('%d/%m/%Y')}",
        "____________________________________________\n"
        f"{company.legal_representative or company.owner_name or 'Empleador / representante autorizado'}\n"
        "Firma del empleador o representante autorizado",
    ])


def build_protocol(
    company: Company, *, responsible: str, channel: str, hours: str,
    rit_status: str,
) -> str:
    """Modelo operativo basado en los mínimos del Anexo I y el orientativo Anexo II."""
    integration = (
        "Este documento se prepara para integrar el Reglamento Interno de Trabajo "
        "como capítulo, sección o anexo. Su generación NO acredita homologación."
        if rit_status in {"homologado", "no_homologado"}
        else "Este protocolo constituye un instrumento independiente de gestión interna "
        "en ausencia de Reglamento Interno de Trabajo."
    )
    sections = [
        ("1. IDENTIFICACIÓN Y VIGENCIA",
         "\n".join(_company_text(company)) + "\n" + integration),
        ("2. OBJETO Y ÁMBITO DE APLICACIÓN",
         "Prevenir, detectar, atender, investigar y corregir hechos de discriminación, "
         "violencia y acoso en el espacio de trabajo. Es aplicable a las relaciones "
         "y situaciones laborales comprendidas en la Resolución MTESS N.º 195/2026 "
         "y su modificatoria N.º 564/2026."),
        ("3. POLÍTICA DE TOLERANCIA CERO",
         f"{company.legal_name} prohíbe la discriminación, violencia y acoso laboral "
         "en todas sus manifestaciones. No se permitirán represalias contra personas "
         "denunciantes de buena fe, testigos o quienes colaboren con la investigación. "
         "El incumplimiento podrá determinar medidas correctivas y sanciones "
         "proporcionales conforme al Código del Trabajo y al RIT vigente, cuando exista."),
        ("4. PRINCIPIOS RECTORES",
         "Confidencialidad, protección, no revictimización, imparcialidad, celeridad, "
         "debido proceso y colaboración. Todas las partes podrán ser oídas y "
         "ofrecer antecedentes; se protegerán sus datos personales."),
        ("5. CONDUCTAS PROHIBIDAS",
         "Entre otras: amenazas, hostigamiento, humillaciones, violencia física, "
         "maltrato psicológico, acoso sexual, discriminación y represalias. "
         "Las conductas se evaluarán según las definiciones y alcances normativos."),
        ("6. INSTANCIA RESPONSABLE",
         f"Persona/instancia designada: {responsible}. "
         "Será responsable de difundir este instrumento, recibir denuncias, "
         "coordinar la prevención, adoptar medidas de protección y conducir "
         "o gestionar la investigación con independencia e imparcialidad."),
        ("7. CANALES DE DENUNCIA",
         f"Canal interno: {channel}. Horario: {hours or 'Horario habitual de la empresa'}. "
         "La denuncia podrá presentarse verbalmente o por escrito, presencialmente "
         "o por medios electrónicos. Para hechos imputados al empleador, máxima "
         "autoridad o representantes, la denuncia deberá dirigirse directamente al MTESS."),
        ("8. DIFUSIÓN Y EXHIBICIÓN",
         "El protocolo estará disponible en formato físico y/o digital en lugares "
         "visibles o medios habituales. Al contratar y periódicamente se informará "
         "de su contenido. Se exhibirán los canales internos y externos de denuncia, "
         "con nombres, contactos y horarios."),
        ("9. PREVENCIÓN Y CAPACITACIÓN",
         "Se realizarán actividades periódicas de formación sobre conductas prohibidas, "
         "derechos y responsabilidades, denuncia y prevención. Las personas "
         "responsables de recibir e investigar denuncias tendrán formación específica."),
        ("10. RECEPCIÓN DE DENUNCIAS",
         "Se recibirá la identificación de las personas involucradas, una descripción "
         "de hechos y fechas aproximadas y los elementos disponibles. Una denuncia "
         "verbal se documentará mediante acta y se entregará copia a la persona denunciante."),
        ("11. MEDIDAS DE RESGUARDO",
         "La empresa adoptará de inmediato medidas adecuadas y proporcionales "
         "para evitar la continuidad del daño y prevenir represalias, sin "
         "perjudicar injustificadamente a las partes involucradas."),
        ("12. INVESTIGACIÓN INTERNA",
         "La investigación se iniciará dentro de los tres días hábiles de recibida "
         "la denuncia. Se informará al MTESS del inicio y de las medidas de resguardo "
         "en los términos y canales establecidos en la normativa vigente. "
         "Se recogerán declaraciones y documentos con confidencialidad, "
         "contradicción, imparcialidad y un expediente de acceso restringido. "
         "Se respetarán los plazos máximos y las reglas de prórroga vigentes."),
        ("13. RESULTADOS Y MEDIDAS CORRECTIVAS",
         "La investigación concluirá con un informe fundado y medidas apropiadas "
         "según los hechos acreditados. Se informará la conclusión al MTESS "
         "dentro del plazo normativo aplicable y se comunicarán las decisiones "
         "a las partes con respeto a la confidencialidad."),
        ("14. PROTECCIÓN Y SEGUIMIENTO",
         "La empresa evaluará la eficacia de las medidas, atenderá eventuales "
         "represalias y revisará periódicamente el protocolo. El cese del vínculo "
         "laboral no extingue por sí solo las obligaciones de investigación."),
        ("15. SITUACIONES CON INTERVENCIÓN DE TERCEROS",
         "Se identificarán y mitigarán los riesgos de violencia de clientes, "
         "usuarios, proveedores y otras personas ajenas a la relación laboral "
         "cuando afecten el espacio de trabajo."),
        ("16. NORMATIVA Y CONTROL DOCUMENTAL",
         "Resoluciones MTESS N.º 195/2026 y N.º 564/2026; Código del Trabajo. "
         "Modelo interno adaptable basado en el Anexo II orientativo oficial. "
         "Requiere revisión y aprobación por el empleador antes de su adopción."),
    ]
    return "\n\n".join(
        ["PROTOCOLO DE PREVENCIÓN, ATENCIÓN E INVESTIGACIÓN DE LA DISCRIMINACIÓN, "
         "VIOLENCIA Y ACOSO EN EL ESPACIO DE TRABAJO"]
        + [f"{heading}\n{text}" for heading, text in sections]
        + [f"{company.city or 'Paraguay'}, {date.today().strftime('%d/%m/%Y')}",
           "____________________________________________\n"
           f"{company.legal_representative or company.owner_name or 'Empleador / representante autorizado'}\n"
           "Firma del empleador o representante autorizado"]
    )


def build_receipt(item: GeneratedCertificate, worker: Employee) -> str:
    """Constancia imprimible, nunca evidencia de firma hasta ser suscrita."""
    return "\n\n".join([
        "CONSTANCIA DE ENTREGA Y RECEPCIÓN DE DOCUMENTO LABORAL",
        f"Empresa: {item.company_name_snapshot}\n"
        f"Trabajador/a: {worker.full_name}\nC.I.: {worker.document_number}\n"
        f"Legajo: {worker.employee_code or 'Sin número'}",
        f"Documento entregado: {item.title}\n"
        f"Versión/documento interno N.º: {item.id}\n"
        f"Fecha de emisión: {item.issue_date.strftime('%d/%m/%Y')}",
        "Declaro haber recibido una copia del documento indicado y haber sido "
        "informado/a de su contenido y de los canales para realizar consultas "
        "o denuncias. La firma acredita recepción, no necesariamente conformidad.",
        "Fecha de entrega: ____/____/________",
        "__________________________           __________________________\n"
        "Firma de recepción del trabajador/a            Firma del responsable de entrega",
    ])


def build_channel_notice(item: GeneratedCertificate) -> str:
    data = decode_metadata(item.observations)
    return "\n\n".join([
        "CANALES DE DENUNCIA Y ORIENTACIÓN",
        "Prevención de la discriminación, violencia y acoso en el espacio de trabajo",
        f"Empresa: {item.company_name_snapshot}",
        f"Responsable: {data.get('responsible', '')}\n"
        f"Canal interno: {data.get('channel', '')}\n"
        f"Horario: {data.get('hours', '') or 'Horario habitual de la empresa'}",
        "Denuncias contra el empleador, máxima autoridad o representantes: "
        "presentarlas directamente ante el MTESS.",
        "Se garantiza confidencialidad, protección y prohibición de represalias "
        "de acuerdo con las disposiciones vigentes.",
        "MTESS: www.mtess.gov.py",
    ])


def _active_employees(db: Session, company_id: int) -> list[Employee]:
    return list(db.scalars(
        select(Employee).where(
            Employee.company_id == company_id,
            func.lower(func.trim(Employee.status)).in_(("activo", "activa")),
            Employee.termination_date.is_(None),
        ).order_by(Employee.full_name.asc(), Employee.id.asc())
    ))


def _export_document(item: GeneratedCertificate, *, kind: str = "main",
                     worker: Employee | None = None) -> ExportData:
    if kind == "main":
        return export_data_from_certificate(item)
    body = build_receipt(item, worker) if kind == "receipt" and worker else build_channel_notice(item)
    label = ("Constancia de recepción" if kind == "receipt" else "Cartel de canales de denuncia")
    return ExportData(
        document_type=DECLARATION if kind == "notice" else "mtess_constancia_recepcion",
        title=label, city=item.city, issue_date=date.today(),
        company_name=item.company_name_snapshot, company_ruc=item.company.ruc,
        company_address=item.company.address,
        legal_representative=item.company.legal_representative or item.company.owner_name,
        employee_name=worker.full_name if worker else "",
        employee_document=worker.document_number if worker else "",
        body=body, status="Borrador",
    )


def register_mtess_routes(app, *, render, require_roles, company_allowed,
                          company_ids_for_user, get_db, write_audit):
    """Se instala al final de main.py, cuando ya están definidos los auxiliares."""
    staff = require_roles("administrador", "contador", "auxiliar")

    def checked_document(db: Session, user, document_id: int) -> GeneratedCertificate:
        item = db.get(GeneratedCertificate, document_id)
        if not item or item.document_type not in TYPES:
            raise HTTPException(404, "Documento MTESS no encontrado.")
        company_allowed(db, user, item.company_id)
        return item

    @app.get("/app/certificates/mtess")
    def mtess_workspace(
        request: Request, company_id: int | None = None,
        user=Depends(staff), db: Session = Depends(get_db),
    ):
        ids = company_ids_for_user(db, user)
        companies = list(db.scalars(
            select(Company).where(Company.id.in_(ids)).order_by(Company.legal_name)
        )) if ids else []
        selected = company_allowed(db, user, company_id) if company_id else (
            companies[0] if companies else None
        )
        workers = _active_employees(db, selected.id) if selected else []
        histories = list(db.scalars(
            select(GeneratedCertificate).where(
                GeneratedCertificate.company_id == selected.id,
                GeneratedCertificate.document_type.in_(TYPES),
            ).order_by(GeneratedCertificate.created_at.desc(), GeneratedCertificate.id.desc()).limit(30)
        )) if selected else []
        latest = histories[0] if histories else None
        config = decode_metadata(latest.observations) if latest else {}
        return render(
            request, "mtess_certificates.html", db, user,
            companies=companies, company=selected, workers=workers,
            active_count=len(workers),
            applicable=applicable_type(len(workers)) if selected else "",
            latest=latest, histories=histories,
            configs=config, labels=LABELS, deadline=DEADLINE,
            source_url=SOURCE_URL,
        )

    @app.post("/app/certificates/mtess/generate")
    def generate_mtess(
        company_id: int = Form(...),
        responsible: str = Form(...),
        channel: str = Form(...),
        hours: str = Form(""),
        rit_status: str = Form("unknown"),
        user=Depends(staff), db: Session = Depends(get_db),
    ):
        company = company_allowed(db, user, company_id)
        responsible, channel, hours = responsible.strip(), channel.strip(), hours.strip()
        if not responsible or not channel:
            raise HTTPException(422, "Indicar responsable y canal de denuncias.")
        if any(len(v) > max_len for v, max_len in (
            (responsible, 160), (channel, 240), (hours, 120)
        )):
            raise HTTPException(422, "Los datos de contacto son demasiado extensos.")
        if rit_status not in {"unknown", "sin", "homologado", "no_homologado"}:
            raise HTTPException(422, "Estado de Reglamento Interno inválido.")
        count = len(_active_employees(db, company.id))
        document_type = applicable_type(count)
        if document_type == PROTOCOL and rit_status == "unknown":
            raise HTTPException(422, "Indicá si la empresa tiene Reglamento Interno de Trabajo.")
        body = (
            build_declaration(company, responsible=responsible, channel=channel, hours=hours)
            if document_type == DECLARATION else
            build_protocol(company, responsible=responsible, channel=channel, hours=hours,
                           rit_status=rit_status)
        )
        prev = db.scalar(select(GeneratedCertificate).where(
            GeneratedCertificate.company_id == company.id,
            GeneratedCertificate.document_type == document_type,
        ).order_by(GeneratedCertificate.id.desc()).limit(1))
        if prev and prev.body == body:
            return RedirectResponse(
                f"/app/certificates/mtess?company_id={company.id}&already=1", status_code=303
            )
        record = GeneratedCertificate(
            company_id=company.id, employee_id=None, document_type=document_type,
            title=LABELS[document_type], city=company.city or "Ciudad del Este",
            issue_date=date.today(), company_name_snapshot=company.legal_name,
            body=body, status="Borrador", created_by=user.email,
            observations=encode_metadata(
                responsible=responsible, channel=channel, hours=hours,
                rit_status=rit_status, worker_count=count,
                legal_basis="MTESS 195/2026 y 564/2026",
                document_version=(decode_metadata(prev.observations).get("document_version", 0) + 1)
                if prev else 1,
                evidence_reference="", evidence_date="",
            ),
        )
        db.add(record)
        db.flush()
        write_audit(db, user, "generar", "documento_mtess", str(record.id),
                    f"{company.legal_name} · {LABELS[document_type]} · {count} activos")
        db.commit()
        return RedirectResponse(
            f"/app/certificates/mtess?company_id={company.id}&created={record.id}",
            status_code=303,
        )

    @app.post("/app/certificates/mtess/{document_id}/evidence")
    def record_document_evidence(
        document_id: int, evidence_reference: str = Form(...),
        evidence_date: date = Form(...), stage: str = Form(...),
        user=Depends(staff), db: Session = Depends(get_db),
    ):
        item = checked_document(db, user, document_id)
        evidence_reference = evidence_reference.strip()
        if stage not in {"Firmado", "Difundido"} or not evidence_reference or len(evidence_reference) > 500:
            raise HTTPException(422, "Debe consignarse una evidencia comprobable y un estado válido.")
        if evidence_date > date.today():
            raise HTTPException(422, "La fecha de evidencia no puede estar en el futuro.")
        meta = decode_metadata(item.observations)
        history = meta.get("evidence_history", [])
        if not isinstance(history, list):
            history = []
        history.append({
            "stage": stage, "reference": evidence_reference,
            "date": evidence_date.isoformat(), "registered_by": user.email,
            "registered_at": datetime.now(UTC).isoformat(),
        })
        item.observations = encode_metadata(
            **{**meta, "evidence_history": history,
               "evidence_reference": evidence_reference,
               "evidence_date": evidence_date.isoformat()},
        )
        # Estado administrativo declarado por el usuario, NO homologación MTESS.
        item.status = stage
        write_audit(db, user, "registrar_evidencia", "documento_mtess", str(item.id),
                    f"{stage}: {evidence_reference}")
        db.commit()
        return RedirectResponse(
            f"/app/certificates/mtess?company_id={item.company_id}&evidence=1",
            status_code=303,
        )

    @app.get("/app/certificates/mtess/{document_id}/download.{extension}")
    def mtess_download(
        document_id: int, extension: str, kind: str = "main",
        employee_id: int | None = None,
        user=Depends(staff), db: Session = Depends(get_db),
    ):
        if extension not in {"pdf", "docx"} or kind not in {"main", "notice", "receipt"}:
            raise HTTPException(404, "Formato no disponible.")
        item = checked_document(db, user, document_id)
        worker = None
        if kind == "receipt":
            if employee_id is None:
                raise HTTPException(422, "Seleccioná un trabajador para la constancia.")
            worker = db.get(Employee, employee_id)
            if not worker or worker.company_id != item.company_id or not is_active_employee(worker):
                raise HTTPException(404, "Funcionario activo no encontrado en la empresa.")
        data = _export_document(item, kind=kind, worker=worker)
        payload = build_pdf_bytes(data) if extension == "pdf" else build_docx_bytes(data)
        name = safe_download_name(data.title, worker.full_name if worker else item.company_name_snapshot,
                                  extension)
        write_audit(db, user, "descargar", "documento_mtess", str(item.id),
                    f"{kind}: {name}")
        db.commit()
        media_type = (
            "application/pdf" if extension == "pdf"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        return StreamingResponse(
            io.BytesIO(payload), media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
        )
