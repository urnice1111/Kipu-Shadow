"""Static vocabularies. Lookups use folded forms (lowercase, no accents)."""

from app.core.text import fold

FEMALE_NAMES = """
Adela Adriana Alba Alejandra Alexandra Alicia Amalia Amparo Ana Andrea Ángela Angélica Antonia Aura
Beatriz Bibiana Blanca Camila Carla Carmen Carolina Catalina Cecilia Celeste Clara Claudia Constanza
Cristina Daniela Diana Dora Doris Elena Elisa Elizabeth Elvira Emilia Erika Esperanza Estefanía Esther
Eugenia Fernanda Flor Francy Gabriela Gloria Graciela Helena Inés Irene Isabel Isabella Ivonne Jazmín
Jennifer Jessica Johana Josefina Juana Judith Julia Juliana Julieth Karen Karina Katherine Kelly Laura
Leidy Lida Liliana Lina Lizeth Lorena Lucía Luisa Luz Manuela Marcela Margarita María Mariana Maribel
Marina Marta Martha Mercedes Milena Mónica Natalia Nidia Nohora Norma Olga Ofelia Pamela Paola Patricia
Paula Pilar Raquel Rocío Rosa Rosario Salomé Sandra Sara Silvia Sofía Sonia Stella Susana Tatiana
Teresa Valentina Valeria Vanessa Verónica Victoria Viviana Ximena Yaneth Yesenia Yolanda Yuliana Zoraida
""".split()

MALE_NAMES = """
Adrián Agustín Alberto Alejandro Alexander Alfonso Alonso Álvaro Andrés Aníbal Antonio Armando Arturo
Benjamín Bernardo Brayan Camilo Carlos César Cristian Dagoberto Daniel Darío David Diego Edgar Eduardo
Emilio Enrique Ernesto Esteban Fabián Farid Federico Felipe Fernando Francisco Gabriel Germán Gilberto
Gonzalo Guillermo Gustavo Héctor Hernán Hernando Horacio Hugo Humberto Ignacio Iván Jaime Javier Jerónimo
Jesús Jhon Jorge José Juan Julián Julio Kevin Leonardo Leonel Lisandro Lorenzo Luis Manuel Marco Mario
Martín Mateo Mauricio Miguel Milton Nelson Nicolás Norberto Octavio Óscar Pablo Pedro Rafael Ramiro Raúl
Ricardo Roberto Rodrigo Rubén Samuel Santiago Sebastián Sergio Simón Tomás Uriel Víctor Wilson Yamid
""".split()

SURNAMES = """
Acosta Agudelo Aguilar Álvarez Arango Arias Aristizábal Ávila Barrera Bedoya Betancur Bolívar Botero
Bustamante Caicedo Calderón Cano Cardona Carmona Carrillo Castaño Castilla Castillo Castro Cifuentes
Córdoba Correa Cortés Cruz Cuéllar Díaz Duque Escobar Espinosa Estrada Franco Galán Gallego Galvis
García Garzón Gaviria Giraldo Gómez González Granados Guerrero Gutiérrez Guzmán Henao Hernández Herrera
Hoyos Jaramillo Jiménez Lozano Londoño López Luna Marín Marulanda Martínez Medina Mejía Mendoza Molina
Montoya Mora Morales Moreno Muñoz Naranjo Navarro Niño Núñez Ocampo Ordóñez Orozco Ortiz Osorio Ospina
Pardo Parra Patiño Peña Pérez Pineda Posada Quintero Ramírez Ramos Restrepo Reyes Ríos Rivera Robledo
Rodríguez Rojas Romero Rueda Ruiz Salazar Salcedo Sánchez Santander Sepúlveda Sierra Silva Suárez
Torres Trujillo Uribe Valencia Vanegas Vargas Vásquez Velásquez Vélez Villa Zambrano Zapata Zuluaga
""".split()

# Pools for pseudonyms; overlap with real names is checked at generation time.
PSEUDO_FEMALE = """
Abigail Adelaida Aída Alba Alicia Ámbar Antonella Aurora Azucena Berenice Brenda Candelaria Celina
Daniella Débora Delia Dulce Elvia Emma Estela Eva Fabiola Fanny Gisela Gladys Hilda Ingrid Iris Jimena
Leonor Lía Lidia Lucero Luciana Maite Mariela Matilde Miriam Nancy Nathalia Nelly Noemí Olivia Penélope
Regina Renata Rebeca Rosalba Rut Selena Silvana Tania Telma Úrsula Vilma Wendy Yadira Zulma
""".split()

PSEUDO_MALE = """
Abel Ángel Arnulfo Bayron Bruno Ciro Clemente Dairo Dionisio Edwin Efraín Eliseo Elkin Emiliano Erasmo
Fausto Fidel Gerardo Guido Harold Ismael Joaquín Leandro Lucas Marcelo Marcos Matías Maximiliano Néstor
Orlando Osvaldo Patricio Rigoberto Rolando Salvador Saúl Teodoro Ulises Valentín Wilmer Yesid
""".split()

PSEUDO_SURNAMES = """
Alzate Amaya Ángel Arbeláez Arboleda Ardila Arteaga Ayala Barón Beltrán Benavides Bermúdez Buitrago
Cadavid Camacho Carvajal Cepeda Chaparro Cuartas Daza Delgado Echeverri Fajardo Forero Fuentes Gil
Hurtado Ibarra Lara León Lozada Manrique Maya Montes Murillo Noreña Olaya Pabón Palacio Peláez Pulido
Quiroga Rendón Rincón Salas Serna Tamayo Toro Urrego Valderrama Vallejo Vega Villegas Yepes Zamora
""".split()

PERSONAL_EMAIL_DOMAINS = ["gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com"]

ROLE_EMAIL_LOCALS = {
    "soporte", "info", "contacto", "notificaciones", "ayuda", "servicio", "servicioalcliente", "pagos",
    "cobranza", "cobros", "legal", "juridica", "talento", "noreply", "no-reply", "fraude", "seguridad",
    "datos", "privacidad", "habeasdata", "pqr", "pqrs", "comercial", "ventas", "facturacion",
    "tesoreria", "riesgo", "auditoria", "compliance", "proveedores", "admin", "it", "mesa",
}

# Organizations, brands, places and public figures that must stay as they are.
KEPT_TERMS = """
Kipu Pay|Kipu|Kipi|Págalo|Pagalo|Bancolombia|Nequi|Daviplata|Davivienda|Banco de Bogotá|Banco de Occidente|
Banco Popular|Banco Agrario|Banco Caja Social|BBVA|Scotiabank Colpatria|Itaú|Banco Falabella|Lulo Bank|
Santander|Seguros Bolívar|Bolívar|Sura|Colsanitas|PSE|Visa|Mastercard|Carulla|Éxito|Olímpica|D1|Jumbo|
Falabella|Rappi|Avianca|Tigo|Claro|Movistar|EPM|Enel|Emcali|Terpel|Farmatodo|Spotify|Netflix|Juan Valdez|
WhatsApp|Google|Gmail|Outlook|Superfinanciera|Superintendencia Financiera|SIC|DIAN|Datacrédito|TransUnion|
Bogotá|Medellín|Cali|Barranquilla|Bucaramanga|Cartagena|Pereira|Manizales|Santa Marta|Cúcuta|Ibagué|
Villavicencio|Pasto|Montería|Neiva|Armenia|Popayán|Envigado|Itagüí|Sabaneta|Dosquebradas|Colombia|
Antioquia|Valle del Cauca|Plaza Botero|Parque de Bolívar|Avenida El Dorado|Los Andes|Feria de las Flores|
Shakira|Gabriel García Márquez|García Márquez|Jorge Isaacs|Fernando Botero|Botero|Simón Bolívar|
Juanes|Carlos Vives|Karol G|Maluma|James Rodríguez|Falcao|Egan Bernal|Nairo Quintana|Rigoberto Urán
""".replace("\n", "").split("|")

KEPT_REASON = "organización, lugar, marca o figura pública; no es persona natural"

OCCUPATION_SECTOR = {
    "abogado": "profesional del derecho",
    "abogada": "profesional del derecho",
    "administrador": "profesional de servicios",
    "administradora": "profesional de servicios",
    "arquitecto": "profesional de la construcción",
    "arquitecta": "profesional de la construcción",
    "auxiliar contable": "profesional de finanzas",
    "chef": "profesional de gastronomía",
    "comerciante": "profesional del comercio",
    "community manager": "profesional de medios",
    "conductor de plataforma": "profesional del transporte",
    "contador": "profesional de finanzas",
    "contadora": "profesional de finanzas",
    "diseñador gráfico": "profesional de las industrias creativas",
    "diseñadora gráfica": "profesional de las industrias creativas",
    "diseñador": "profesional de las industrias creativas",
    "diseñadora": "profesional de las industrias creativas",
    "contador público": "profesional de finanzas",
    "contadora pública": "profesional de finanzas",
    "ingeniero": "profesional de ingeniería",
    "ingeniera": "profesional de ingeniería",
    "ingeniero industrial": "profesional de ingeniería",
    "ingeniera industrial": "profesional de ingeniería",
    "estudiante": "estudiante universitario",
    "docente": "profesional de la educación",
    "profesor": "profesional de la educación",
    "profesora": "profesional de la educación",
    "electricista": "profesional técnico",
    "enfermera": "profesional de la salud",
    "enfermero": "profesional de la salud",
    "estilista": "profesional de servicios",
    "estudiante de derecho": "estudiante universitario",
    "estudiante de medicina": "estudiante universitario",
    "fisioterapeuta": "profesional de la salud",
    "fotógrafa": "profesional de las industrias creativas",
    "fotógrafo": "profesional de las industrias creativas",
    "ingeniera de sistemas": "profesional de tecnología",
    "ingeniero de sistemas": "profesional de tecnología",
    "ingeniero civil": "profesional de la construcción",
    "ingeniera civil": "profesional de la construcción",
    "mecánico": "profesional del transporte",
    "mecánica": "profesional del transporte",
    "odontóloga": "profesional de la salud",
    "odontólogo": "profesional de la salud",
    "panadero": "profesional de gastronomía",
    "panadera": "profesional de gastronomía",
    "periodista": "profesional de medios",
    "piloto comercial": "profesional del transporte",
    "piloto": "profesional del transporte",
    "psicóloga": "profesional de la salud",
    "psicólogo": "profesional de la salud",
    "veterinaria": "profesional de la salud",
    "veterinario": "profesional de la salud",
    "médico": "profesional de la salud",
    "médica": "profesional de la salud",
}

HONORIFIC_WORDS = {"sr", "sra", "senor", "senora", "don", "dona", "doctor", "doctora", "dr", "dra"}

# Capitalized words that start sentences or name things and are never given names here.
NOT_NAME_WORDS = {
    "hola", "buenas", "buenos", "gracias", "listo", "claro", "perfecto", "cliente", "clienta", "señor",
    "señora", "equipo", "compra", "pago", "retiro", "transferencia", "cuota", "banco", "tarjeta",
}


def folded_set(words) -> set[str]:
    return {fold(w) for w in words}


WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
    "noviembre", "diciembre",
]
ROLE_WORDS = """agente analista coordinador coordinadora gerente director directora abogado abogada contador
contadora auditor auditora socio socia representante legal externo externa senior junior líder jefe jefa
asesor asesora ingeniero ingeniera""".split()
NOT_NAME_WORDS = (
    folded_set(NOT_NAME_WORDS)
    | folded_set(WEEKDAYS + MONTHS + ROLE_WORDS)
    | {w for k in OCCUPATION_SECTOR for w in folded_set(k.split())}
)

# Given names that are also everyday words: lowercase, they only count as names right after a greeting.
COMMON_WORD_NAMES = folded_set(
    """rosa luz pilar paz alba gloria victoria esperanza consuelo amparo dolores mercedes soledad cruz
    ángel ángeles rocío milagros socorro concepción belén reyes salvador domingo fe flor azucena margarita
    violeta aurora celeste clemente franco blanca cielo estrella sol perla nieves leal dulce linda bella
    marina justo fidel modesto prudencia libertad patria inocencio feliz alegría rey mar alma paloma jade
    abril julio clara tomás marco césar pastor santos león rosario gracia iris rubí""".split()
)

FEMALE = folded_set(FEMALE_NAMES)
MALE = folded_set(MALE_NAMES)
GIVEN = FEMALE | MALE
SURNAME_SET = folded_set(SURNAMES)


def gender_of(first_given: str) -> str:
    f = fold(first_given)
    if f in FEMALE and f not in MALE:
        return "F"
    if f in MALE:
        return "M"
    return "F" if f.endswith("a") else "M"
