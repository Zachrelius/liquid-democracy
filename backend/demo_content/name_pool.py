"""Phase 23 (Amendment C) — name pool for filler member generation.

Curated list of plausible American first + last name combos used by
``filler_generator.generate_filler_members`` to populate ~50-60 filler
members per demo org beyond the bible's named characters. Diverse mix of
backgrounds; not deterministically tied to any particular org.

The pool is intentionally larger than per-org filler counts so the
deterministic per-org PRNG can pick distinct subsets without exhaustion
(3 orgs × 55 fillers = 165 picks < 200 entries).
"""
from __future__ import annotations


NAME_POOL: list[tuple[str, str]] = [
    # White (Anglo) — common American names
    ("Sarah", "Johnson"), ("Michael", "Smith"), ("Emily", "Brown"),
    ("David", "Miller"), ("Jessica", "Davis"), ("Daniel", "Wilson"),
    ("Ashley", "Anderson"), ("Christopher", "Taylor"), ("Amanda", "Thomas"),
    ("Matthew", "Moore"), ("Jennifer", "Martin"), ("Andrew", "Jackson"),
    ("Megan", "White"), ("Joshua", "Harris"), ("Lauren", "Thompson"),
    ("Brandon", "Garcia"), ("Stephanie", "Lewis"), ("Justin", "Walker"),
    ("Heather", "Hall"), ("Ryan", "Young"), ("Nicole", "Allen"),
    ("Tyler", "King"), ("Rachel", "Wright"), ("Brian", "Scott"),
    ("Samantha", "Green"), ("Jason", "Baker"), ("Katherine", "Adams"),
    ("Eric", "Nelson"), ("Christina", "Carter"), ("Aaron", "Mitchell"),
    ("Laura", "Roberts"), ("Adam", "Turner"), ("Megan", "Phillips"),
    ("Kevin", "Campbell"), ("Allison", "Parker"), ("Joseph", "Evans"),
    ("Hannah", "Edwards"), ("Patrick", "Collins"), ("Olivia", "Stewart"),
    ("Nathan", "Morris"), ("Madison", "Rogers"), ("Steven", "Reed"),
    ("Brittany", "Cook"), ("Robert", "Morgan"), ("Kayla", "Bell"),
    ("Thomas", "Murphy"), ("Victoria", "Bailey"), ("Charles", "Rivera"),
    ("Danielle", "Cooper"), ("Anthony", "Richardson"),

    # Black / African-American
    ("Aisha", "Williams"), ("DeAndre", "Jefferson"), ("Tanya", "Washington"),
    ("Marcus", "Robinson"), ("Imani", "Booker"), ("Jamal", "Carter"),
    ("Keisha", "Henderson"), ("Terrell", "Bell"), ("Latoya", "Mosley"),
    ("Andre", "Mitchell"), ("Crystal", "Banks"), ("Reggie", "Wallace"),
    ("Tyrone", "Brooks"), ("Nia", "Coleman"), ("Darnell", "Howard"),
    ("Brianna", "Wright"), ("Devin", "Greene"), ("Ebony", "Watkins"),
    ("Maurice", "Harris"), ("Tia", "Lawson"),

    # Latino / Hispanic
    ("Carlos", "Martinez"), ("Lucia", "Hernandez"), ("Diego", "Lopez"),
    ("Maria", "Gonzalez"), ("Javier", "Rodriguez"), ("Sofia", "Perez"),
    ("Miguel", "Ramirez"), ("Camila", "Flores"), ("Andres", "Torres"),
    ("Isabella", "Rivera"), ("Ricardo", "Gomez"), ("Elena", "Sanchez"),
    ("Fernando", "Reyes"), ("Valentina", "Cruz"), ("Hugo", "Ortiz"),
    ("Daniela", "Castillo"), ("Sergio", "Mendoza"), ("Gabriela", "Vargas"),
    ("Esteban", "Aguilar"), ("Adriana", "Jimenez"), ("Mateo", "Rojas"),
    ("Carmen", "Delgado"), ("Rafael", "Salazar"), ("Lourdes", "Pena"),

    # East Asian
    ("Wei", "Chen"), ("Yuki", "Tanaka"), ("Min-ji", "Park"),
    ("Hiroshi", "Sato"), ("Mei", "Wang"), ("Jun", "Kim"),
    ("Ling", "Liu"), ("Kenji", "Watanabe"), ("Soo-yeon", "Lee"),
    ("Xiao", "Zhang"), ("Akira", "Yamamoto"), ("Hye-jin", "Choi"),
    ("Bao", "Nguyen"), ("Linh", "Tran"), ("Hoa", "Vo"),
    ("Tuan", "Pham"), ("Anh", "Le"), ("Quynh", "Hoang"),

    # South Asian
    ("Priya", "Sharma"), ("Raj", "Patel"), ("Ananya", "Kumar"),
    ("Arjun", "Singh"), ("Neha", "Gupta"), ("Vikram", "Mehta"),
    ("Deepika", "Reddy"), ("Sanjay", "Iyer"), ("Pooja", "Joshi"),
    ("Kiran", "Desai"), ("Ravi", "Nair"), ("Anika", "Banerjee"),
    ("Rohit", "Agarwal"), ("Shreya", "Rao"), ("Aditya", "Verma"),

    # Middle Eastern / Arab
    ("Omar", "Hassan"), ("Layla", "Khalil"), ("Karim", "Mansour"),
    ("Fatima", "Ahmed"), ("Yasmin", "Saleh"), ("Tariq", "Nasser"),
    ("Mariam", "Farah"), ("Sami", "Haddad"),

    # Eastern European / Slavic
    ("Anya", "Petrov"), ("Mikhail", "Volkov"), ("Katarzyna", "Kowalski"),
    ("Dmitri", "Sokolov"), ("Magdalena", "Nowak"), ("Aleksandr", "Ivanov"),
    ("Olga", "Bauer"), ("Pavel", "Kozlov"),

    # Italian / Southern European
    ("Antonio", "Russo"), ("Giulia", "Bianchi"), ("Marco", "Romano"),
    ("Francesca", "Conti"), ("Luca", "Greco"), ("Chiara", "Marino"),

    # Jewish
    ("Rachel", "Goldberg"), ("Aaron", "Bernstein"), ("Sarah", "Cohen"),
    ("Daniel", "Feldman"), ("Hannah", "Rosen"), ("Ethan", "Schwartz"),
    ("Naomi", "Kaplan"), ("Joshua", "Stein"),

    # Mixed / other
    ("Quinn", "OConnor"), ("Riley", "Murphy"), ("Jordan", "Kelly"),
    ("Casey", "Sullivan"), ("Morgan", "Fitzgerald"), ("Avery", "OBrien"),
    ("Jamie", "Lynch"), ("Cameron", "Walsh"), ("Drew", "Kennedy"),
    ("Skyler", "Doyle"), ("Reese", "Gallagher"), ("Hayden", "Burke"),
    ("Logan", "Riley"), ("Bailey", "Quinn"), ("Sage", "Bradley"),

    # More for buffer
    ("Eleanor", "Hughes"), ("Henry", "Foster"), ("Ruby", "Powell"),
    ("Oscar", "Bryant"), ("Lily", "Sanders"), ("Felix", "Price"),
    ("Iris", "Long"), ("Theodore", "Ross"), ("Vivian", "Hayes"),
    ("Leo", "Wood"), ("Stella", "Barnes"), ("Atlas", "Coleman"),
    ("Zora", "Webb"), ("Felix", "Tucker"), ("June", "Holt"),
    ("Silas", "Burns"), ("Wren", "Hawkins"), ("Cyrus", "Vaughn"),
    ("Mira", "Klein"), ("Bruno", "Acosta"),
]


__all__ = ["NAME_POOL"]
