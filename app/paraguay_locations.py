"""Curated Paraguayan departments and districts used by the company maintenance form."""

PARAGUAY_DEPARTMENTS = [
    "Asunción", "Concepción", "San Pedro", "Cordillera", "Guairá", "Caaguazú",
    "Caazapá", "Itapúa", "Misiones", "Paraguarí", "Alto Paraná", "Central",
    "Ñeembucú", "Amambay", "Canindeyú", "Presidente Hayes", "Boquerón", "Alto Paraguay",
]

_PARAGUAY_CITY_ROWS = [
    ("Asunción", "Asunción"),
    ("Concepción", "Concepción"), ("Horqueta", "Concepción"), ("Yby Yaú", "Concepción"), ("Loreto", "Concepción"), ("Belén", "Concepción"), ("San Lázaro", "Concepción"),
    ("San Pedro de Ycuamandyyú", "San Pedro"), ("San Estanislao", "San Pedro"), ("Santa Rosa del Aguaray", "San Pedro"), ("Itacurubí del Rosario", "San Pedro"), ("General Aquino", "San Pedro"), ("Capiibary", "San Pedro"),
    ("Caacupé", "Cordillera"), ("Altos", "Cordillera"), ("Atyrá", "Cordillera"), ("Eusebio Ayala", "Cordillera"), ("Piribebuy", "Cordillera"), ("Tobatí", "Cordillera"), ("Itacurubí de la Cordillera", "Cordillera"),
    ("Villarrica", "Guairá"), ("Independencia", "Guairá"), ("Mbocayaty", "Guairá"), ("Iturbe", "Guairá"), ("Paso Yobái", "Guairá"), ("Natalicio Talavera", "Guairá"),
    ("Coronel Oviedo", "Caaguazú"), ("Caaguazú", "Caaguazú"), ("Doctor Juan Manuel Frutos", "Caaguazú"), ("J. Eulogio Estigarribia", "Caaguazú"), ("Repatriación", "Caaguazú"), ("San José de los Arroyos", "Caaguazú"),
    ("Caazapá", "Caazapá"), ("San Juan Nepomuceno", "Caazapá"), ("Yuty", "Caazapá"), ("Abaí", "Caazapá"), ("Tavaí", "Caazapá"),
    ("Encarnación", "Itapúa"), ("Cambyretá", "Itapúa"), ("Hohenau", "Itapúa"), ("Obligado", "Itapúa"), ("Bella Vista", "Itapúa"), ("Fram", "Itapúa"), ("Capitán Miranda", "Itapúa"), ("Coronel Bogado", "Itapúa"), ("San Juan del Paraná", "Itapúa"), ("Tomás Romero Pereira", "Itapúa"),
    ("San Juan Bautista", "Misiones"), ("San Ignacio", "Misiones"), ("Ayolas", "Misiones"), ("Santa Rosa", "Misiones"), ("Santiago", "Misiones"), ("Santa María", "Misiones"),
    ("Paraguarí", "Paraguarí"), ("Carapeguá", "Paraguarí"), ("Yaguarón", "Paraguarí"), ("Quiindy", "Paraguarí"), ("Pirayú", "Paraguarí"), ("Acahay", "Paraguarí"),
    ("Ciudad del Este", "Alto Paraná"), ("Hernandarias", "Alto Paraná"), ("Presidente Franco", "Alto Paraná"), ("Minga Guazú", "Alto Paraná"), ("Santa Rita", "Alto Paraná"), ("Juan León Mallorquín", "Alto Paraná"), ("Itakyry", "Alto Paraná"), ("San Alberto", "Alto Paraná"), ("Naranjal", "Alto Paraná"), ("Mbaracayú", "Alto Paraná"), ("Domingo Martínez de Irala", "Alto Paraná"),
    ("Areguá", "Central"), ("Capiatá", "Central"), ("Fernando de la Mora", "Central"), ("Luque", "Central"), ("Lambaré", "Central"), ("Limpio", "Central"), ("Mariano Roque Alonso", "Central"), ("Ñemby", "Central"), ("San Lorenzo", "Central"), ("Villa Elisa", "Central"), ("Itauguá", "Central"), ("Ypané", "Central"), ("J. Augusto Saldívar", "Central"), ("Guarambaré", "Central"), ("Villeta", "Central"), ("Nueva Italia", "Central"), ("Itá", "Central"),
    ("Pilar", "Ñeembucú"), ("Alberdi", "Ñeembucú"), ("Cerrito", "Ñeembucú"), ("Humaitá", "Ñeembucú"), ("Villa Franca", "Ñeembucú"), ("Villalbín", "Ñeembucú"),
    ("Pedro Juan Caballero", "Amambay"), ("Bella Vista Norte", "Amambay"), ("Capitán Bado", "Amambay"), ("Zanja Pytã", "Amambay"),
    ("Salto del Guairá", "Canindeyú"), ("Curuguaty", "Canindeyú"), ("Katueté", "Canindeyú"), ("Nueva Esperanza", "Canindeyú"), ("Yby Pytã", "Canindeyú"), ("Corpus Christi", "Canindeyú"),
    ("Villa Hayes", "Presidente Hayes"), ("Benjamín Aceval", "Presidente Hayes"), ("Nanawa", "Presidente Hayes"), ("Puerto Pinasco", "Presidente Hayes"), ("Teniente Irala Fernández", "Presidente Hayes"),
    ("Filadelfia", "Boquerón"), ("Loma Plata", "Boquerón"), ("Mariscal José Félix Estigarribia", "Boquerón"),
    ("Fuerte Olimpo", "Alto Paraguay"), ("Puerto Casado", "Alto Paraguay"), ("Bahía Negra", "Alto Paraguay"), ("Carmelo Peralta", "Alto Paraguay"),
]

PARAGUAY_CITIES = [{"name": name, "department": department} for name, department in _PARAGUAY_CITY_ROWS]
PARAGUAY_CITY_NAMES = {city["name"] for city in PARAGUAY_CITIES}
