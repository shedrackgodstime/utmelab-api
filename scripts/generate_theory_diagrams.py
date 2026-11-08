import os
import json

DIAGRAMS_DIR = 'data/theory/diagrams'
os.makedirs(DIAGRAMS_DIR, exist_ok=True)

def save_svg(name, svg_content):
    path = os.path.join(DIAGRAMS_DIR, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg_content.strip())
    return f"theory/diagrams/{name}"

diagrams = {}

# 1. Physics Q1: Aerofoil Wing
diagrams['wq_waec_2023_phys_p2_q1'] = save_svg('waec_phys_2023_q1_aerofoil.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb"/>
    </marker>
    <marker id="arr-dark" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#0f172a"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Aerodynamic Force on Aircraft Wing (WAEC Physics 2023 SC5052)</text>
  
  <!-- Airflow lines -->
  <path d="M 50 140 Q 200 80 400 130 T 550 160" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="6,4"/>
  <path d="M 50 170 Q 200 120 400 170 T 550 190" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="6,4"/>
  <path d="M 50 250 Q 250 260 550 240" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="6,4"/>
  <line x1="50" y1="120" x2="120" y2="120" stroke="#2563eb" stroke-width="2.5" marker-end="url(#arr)"/>
  <text x="85" y="110" font-family="sans-serif" font-size="14" font-weight="bold" fill="#2563eb">Air Velocity v, Density ρ</text>

  <!-- Aerofoil Wing Shape -->
  <path d="M 160 210 C 180 140, 280 140, 440 210 C 350 230, 220 235, 160 210 Z" fill="#e2e8f0" stroke="#0f172a" stroke-width="3"/>
  <text x="300" y="200" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a" text-anchor="middle">Wing Surface Area A</text>

  <!-- Force Vector F -->
  <line x1="300" y1="190" x2="300" y2="70" stroke="#dc2626" stroke-width="3.5" marker-end="url(#arr-dark)"/>
  <text x="315" y="100" font-family="sans-serif" font-size="16" font-weight="bold" fill="#dc2626">Aerodynamic Force F</text>
  
  <text x="300" y="340" font-family="sans-serif" font-size="13" fill="#475569" text-anchor="middle">Dimensional formula: F = k · v^x · ρ^y · A^z  |  Evaluated: x = 2, y = 1, z = 1</text>
</svg>
''')

# 2. Physics Q2: Strain Energy Graph
diagrams['wq_waec_2023_phys_p2_q2'] = save_svg('waec_phys_2023_q2_strain_energy.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-axis" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#0f172a"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Tensile Force - Extension Graph and Strain Energy</text>
  
  <!-- Axes -->
  <line x1="100" y1="300" x2="520" y2="300" stroke="#0f172a" stroke-width="2.5" marker-end="url(#arr-axis)"/>
  <line x1="100" y1="300" x2="100" y2="70" stroke="#0f172a" stroke-width="2.5" marker-end="url(#arr-axis)"/>
  <text x="535" y="305" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">Extension e</text>
  <text x="95" y="55" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a" text-anchor="middle">Tensile Force F</text>
  <text x="85" y="315" font-family="sans-serif" font-size="14" fill="#0f172a">0</text>

  <!-- Shaded triangular area for Strain Energy -->
  <polygon points="100,300 420,120 420,300" fill="#dbeafe" stroke="none"/>
  
  <!-- Force line -->
  <line x1="100" y1="300" x2="420" y2="120" stroke="#2563eb" stroke-width="3"/>
  <circle cx="420" cy="120" r="4" fill="#2563eb"/>
  
  <!-- Projections -->
  <line x1="420" y1="120" x2="420" y2="300" stroke="#64748b" stroke-width="1.5" stroke-dasharray="4,4"/>
  <line x1="100" y1="120" x2="420" y2="120" stroke="#64748b" stroke-width="1.5" stroke-dasharray="4,4"/>
  <text x="420" y="325" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a" text-anchor="middle">e</text>
  <text x="75" y="125" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">F</text>
  
  <text x="280" y="240" font-family="sans-serif" font-size="15" font-weight="bold" fill="#1e40af" text-anchor="middle">Strain Energy E = ½ F · e</text>
  <text x="280" y="265" font-family="sans-serif" font-size="13" fill="#1e40af" text-anchor="middle">In terms of Young Modulus: E = (Y · A · e²) / 2l</text>
  <text x="300" y="360" font-family="sans-serif" font-size="12" fill="#64748b" text-anchor="middle">WAEC Physics 2023 SC5052: Elastic Properties of Solids</text>
</svg>
''')

# 3. Physics Q3: Metre Rule Knife Edge Equilibrium
diagrams['wq_waec_2023_phys_p2_q3'] = save_svg('waec_phys_2023_q3_knife_edge.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-f" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#dc2626"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Equilibrium of Uniform Metre Rule on Knife Edge</text>

  <!-- Metre rule beam -->
  <rect x="60" y="140" width="480" height="24" fill="#fef08a" stroke="#ca8a04" stroke-width="2" rx="3"/>
  <text x="65" y="157" font-family="sans-serif" font-size="11" fill="#854d0e">0 cm</text>
  <text x="500" y="157" font-family="sans-serif" font-size="11" fill="#854d0e">100 cm</text>

  <!-- Pivot Knife Edge at 40 cm (x = 60 + 40*4.8 = 252) -->
  <polygon points="252,164 240,210 264,210" fill="#475569" stroke="#0f172a" stroke-width="2"/>
  <rect x="230" y="210" width="44" height="15" fill="#334155" rx="2"/>
  <text x="252" y="240" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Knife Edge (40 cm)</text>

  <!-- Unknown mass m at 10 cm (x = 60 + 10*4.8 = 108) -->
  <line x1="108" y1="164" x2="108" y2="220" stroke="#0f172a" stroke-width="2"/>
  <rect x="90" y="220" width="36" height="30" fill="#3b82f6" stroke="#1d4ed8" stroke-width="2" rx="4"/>
  <text x="108" y="240" font-family="sans-serif" font-size="13" font-weight="bold" fill="#ffffff" text-anchor="middle">m</text>
  <text x="108" y="270" font-family="sans-serif" font-size="12" fill="#1e3a8a" text-anchor="middle">Mass m (10 cm)</text>
  <line x1="108" y1="140" x2="108" y2="90" stroke="#dc2626" stroke-width="2" marker-end="url(#arr-f)"/>
  <text x="108" y="80" font-family="sans-serif" font-size="12" font-weight="bold" fill="#dc2626" text-anchor="middle">m · g</text>

  <!-- Centre of Gravity at 50 cm (x = 60 + 50*4.8 = 300) -->
  <circle cx="300" cy="152" r="5" fill="#dc2626"/>
  <line x1="300" y1="164" x2="300" y2="230" stroke="#dc2626" stroke-width="2.5" marker-end="url(#arr-f)"/>
  <text x="300" y="250" font-family="sans-serif" font-size="13" font-weight="bold" fill="#dc2626" text-anchor="middle">Rule Weight W = 100 g</text>
  <text x="300" y="130" font-family="sans-serif" font-size="12" fill="#475569" text-anchor="middle">C.G. (50 cm)</text>

  <!-- Dimension arms -->
  <line x1="108" y1="110" x2="252" y2="110" stroke="#2563eb" stroke-width="1.5"/>
  <text x="180" y="105" font-family="sans-serif" font-size="12" font-weight="bold" fill="#2563eb" text-anchor="middle">Arm = 30 cm</text>
  <line x1="252" y1="110" x2="300" y2="110" stroke="#16a34a" stroke-width="1.5"/>
  <text x="276" y="105" font-family="sans-serif" font-size="12" font-weight="bold" fill="#16a34a" text-anchor="middle">10 cm</text>

  <text x="300" y="340" font-family="sans-serif" font-size="13" fill="#0f172a" text-anchor="middle">Principle of Moments: m × (40 - 10) = 100 × (50 - 40)  ⟹  m = 33.3 g</text>
</svg>
''')

# 4. Physics Q4: Simple Pendulum SHM
diagrams['wq_waec_2023_phys_p2_q4'] = save_svg('waec_phys_2023_q4_pendulum.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-blue" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb"/>
    </marker>
    <marker id="arr-red" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#dc2626"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Simple Harmonic Motion of a Simple Pendulum</text>

  <!-- Ceiling support -->
  <line x1="220" y1="70" x2="380" y2="70" stroke="#334155" stroke-width="3"/>
  <line x1="300" y1="70" x2="300" y2="290" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="5,5"/>
  <text x="300" y="310" font-family="sans-serif" font-size="13" fill="#64748b" text-anchor="middle">Equilibrium Position</text>

  <!-- Displaced string -->
  <line x1="300" y1="70" x2="420" y2="240" stroke="#0f172a" stroke-width="2.5"/>
  <text x="380" y="150" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">Length l</text>

  <!-- Angle theta -->
  <path d="M 300 130 A 60 60 0 0 1 330 120" fill="none" stroke="#2563eb" stroke-width="2"/>
  <text x="325" y="145" font-family="sans-serif" font-size="14" font-weight="bold" fill="#2563eb">θ</text>

  <!-- Bob at displaced position -->
  <circle cx="420" cy="240" r="18" fill="#3b82f6" stroke="#1d4ed8" stroke-width="2.5"/>
  <text x="420" y="245" font-family="sans-serif" font-size="12" font-weight="bold" fill="#ffffff" text-anchor="middle">m</text>

  <!-- Restoring force vector -->
  <line x1="420" y1="240" x2="340" y2="265" stroke="#dc2626" stroke-width="3" marker-end="url(#arr-red)"/>
  <text x="340" y="295" font-family="sans-serif" font-size="13" font-weight="bold" fill="#dc2626">F = -mg sin θ</text>

  <!-- Weight mg -->
  <line x1="420" y1="240" x2="420" y2="330" stroke="#0f172a" stroke-width="2" marker-end="url(#arr-blue)"/>
  <text x="435" y="325" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a">mg</text>

  <text x="300" y="360" font-family="sans-serif" font-size="13" fill="#0f172a" text-anchor="middle">For small angles (sin θ ≈ θ = x/l), Restoring Force ∝ Displacement  ⟹  SHM</text>
</svg>
''')

# 5. Physics Q5: DC Circuit
diagrams['wq_waec_2023_phys_p2_q5'] = save_svg('waec_phys_2023_q5_dc_circuit.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-i" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Direct Current Series Circuit (E.M.F. and Internal Resistance)</text>

  <!-- Circuit rectangle -->
  <rect x="120" y="80" width="360" height="200" fill="none" stroke="#334155" stroke-width="2.5" rx="4"/>

  <!-- Battery symbol at top -->
  <rect x="270" y="65" width="60" height="30" fill="#f8fafc" stroke="none"/>
  <line x1="285" y1="70" x2="285" y2="90" stroke="#0f172a" stroke-width="3.5"/>
  <line x1="297" y1="75" x2="297" y2="85" stroke="#0f172a" stroke-width="2"/>
  <text x="275" y="60" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a">+</text>
  <text x="305" y="60" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a">-</text>
  <text x="300" y="115" font-family="sans-serif" font-size="13" font-weight="bold" fill="#2563eb" text-anchor="middle">Battery (E, r)</text>

  <!-- Current arrow -->
  <line x1="180" y1="80" x2="210" y2="80" stroke="#2563eb" stroke-width="2.5" marker-end="url(#arr-i)"/>
  <text x="195" y="70" font-family="sans-serif" font-size="13" font-weight="bold" fill="#2563eb">I</text>

  <!-- Series Ammeter on left -->
  <rect x="100" y="160" width="40" height="40" fill="#f8fafc" stroke="none"/>
  <circle cx="120" cy="180" r="18" fill="#ffffff" stroke="#0f172a" stroke-width="2"/>
  <text x="120" y="186" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a" text-anchor="middle">A</text>
  <text x="80" y="185" font-family="sans-serif" font-size="12" fill="#475569">Ammeter</text>

  <!-- External Resistor R at bottom -->
  <rect x="260" y="265" width="80" height="30" fill="#ffffff" stroke="#0f172a" stroke-width="2.5"/>
  <text x="300" y="285" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a" text-anchor="middle">R</text>
  <text x="300" y="320" font-family="sans-serif" font-size="12" fill="#475569" text-anchor="middle">External Resistor R = 4.0 Ω</text>

  <text x="300" y="355" font-family="sans-serif" font-size="13" fill="#0f172a" text-anchor="middle">Circuit Formula: E = I · (R + r) = V + I · r</text>
</svg>
''')

# 6. Physics Q8: Projectile Trajectory
diagrams['wq_waec_2023_phys_p2_q8'] = save_svg('waec_phys_2023_q8_projectile.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-proj" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Projectile Motion Trajectory (WAEC Physics 2023 SC5052)</text>

  <!-- Ground line -->
  <line x1="60" y1="280" x2="540" y2="280" stroke="#0f172a" stroke-width="2.5"/>

  <!-- Parabolic curve -->
  <path d="M 100 280 Q 280 40 460 280" fill="none" stroke="#2563eb" stroke-width="3"/>

  <!-- Launch velocity vector -->
  <line x1="100" y1="280" x2="190" y2="180" stroke="#dc2626" stroke-width="3" marker-end="url(#arr-proj)"/>
  <text x="130" y="190" font-family="sans-serif" font-size="14" font-weight="bold" fill="#dc2626">u = 40 m/s</text>

  <!-- Angle theta -->
  <path d="M 140 280 A 40 40 0 0 0 135 240" fill="none" stroke="#0f172a" stroke-width="2"/>
  <text x="155" y="265" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">30°</text>

  <!-- Apex Maximum Height -->
  <line x1="280" y1="100" x2="280" y2="280" stroke="#059669" stroke-width="2" stroke-dasharray="5,5"/>
  <circle cx="280" cy="100" r="5" fill="#059669"/>
  <text x="295" y="180" font-family="sans-serif" font-size="14" font-weight="bold" fill="#059669">H = 20.0 m</text>
  <text x="280" y="90" font-family="sans-serif" font-size="12" fill="#059669" text-anchor="middle">Apex (v_y = 0, t = 2.0 s)</text>

  <!-- Range R -->
  <line x1="100" y1="310" x2="460" y2="310" stroke="#0f172a" stroke-width="2"/>
  <line x1="100" y1="305" x2="100" y2="315" stroke="#0f172a" stroke-width="2"/>
  <line x1="460" y1="305" x2="460" y2="315" stroke="#0f172a" stroke-width="2"/>
  <text x="280" y="335" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a" text-anchor="middle">Horizontal Range R = 138.56 m</text>
</svg>
''')

# 7. Chemistry Q4: Electrolytic Copper Refining
diagrams['wq_waec_2023_chem_p2_q4'] = save_svg('waec_chem_2023_q4_copper_refining.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-chem" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Electrolytic Refining of Impure Copper</text>

  <!-- Electrolytic tank -->
  <rect x="120" y="110" width="360" height="180" fill="#dbeafe" stroke="#0f172a" stroke-width="2.5" rx="4"/>
  <text x="300" y="275" font-family="sans-serif" font-size="13" font-weight="bold" fill="#1e40af" text-anchor="middle">Acidified Aqueous CuSO4 Electrolyte</text>

  <!-- Anode (Impure Blister Copper) -->
  <rect x="180" y="80" width="35" height="170" fill="#b45309" stroke="#78350f" stroke-width="2"/>
  <text x="197" y="70" font-family="sans-serif" font-size="13" font-weight="bold" fill="#78350f" text-anchor="middle">Anode (+)</text>
  <text x="197" y="170" font-family="sans-serif" font-size="11" fill="#ffffff" text-anchor="middle">Impure</text>
  <text x="197" y="185" font-family="sans-serif" font-size="11" fill="#ffffff" text-anchor="middle">Blister Cu</text>

  <!-- Cathode (Pure Copper Sheet) -->
  <rect x="385" y="80" width="20" height="170" fill="#ea580c" stroke="#9a3412" stroke-width="2"/>
  <text x="395" y="70" font-family="sans-serif" font-size="13" font-weight="bold" fill="#9a3412" text-anchor="middle">Cathode (-)</text>
  <text x="395" y="170" font-family="sans-serif" font-size="11" fill="#ffffff" text-anchor="middle">Pure Cu</text>

  <!-- Connecting Wires and DC supply -->
  <polyline points="197,80 197,55 270,55" fill="none" stroke="#0f172a" stroke-width="2"/>
  <polyline points="400,55 395,55 395,80" fill="none" stroke="#0f172a" stroke-width="2"/>
  <!-- DC power symbol -->
  <line x1="270" y1="45" x2="270" y2="65" stroke="#0f172a" stroke-width="3"/>
  <line x1="280" y1="50" x2="280" y2="60" stroke="#0f172a" stroke-width="2"/>
  <line x1="280" y1="55" x2="400" y2="55" stroke="#0f172a" stroke-width="2"/>
  <text x="260" y="45" font-family="sans-serif" font-size="12" font-weight="bold" fill="#0f172a">+</text>
  <text x="290" y="45" font-family="sans-serif" font-size="12" font-weight="bold" fill="#0f172a">-</text>

  <!-- Anode Sludge -->
  <ellipse cx="197" cy="275" rx="25" ry="8" fill="#713f12"/>
  <text x="140" y="315" font-family="sans-serif" font-size="12" fill="#713f12">Anode Sludge (Ag, Au)</text>

  <!-- Cu2+ Ion Migration -->
  <line x1="240" y1="160" x2="350" y2="160" stroke="#2563eb" stroke-width="2.5" marker-end="url(#arr-chem)"/>
  <text x="295" y="150" font-family="sans-serif" font-size="13" font-weight="bold" fill="#2563eb" text-anchor="middle">Cu²⁺ (aq) Migration</text>

  <text x="300" y="355" font-family="sans-serif" font-size="13" fill="#0f172a" text-anchor="middle">Cathode Half-Reaction: Cu²⁺(aq) + 2e⁻ ⟶ Cu(s, pure)</text>
</svg>
''')

# 8. Chemistry Q7: Haber Process Energy Profile
diagrams['wq_waec_2023_chem_p2_q7'] = save_svg('waec_chem_2023_q7_haber_energy.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-axis-chem" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#0f172a"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Energy Profile Diagram for Ammonia Synthesis (Haber Process)</text>

  <!-- Axes -->
  <line x1="80" y1="310" x2="520" y2="310" stroke="#0f172a" stroke-width="2.5" marker-end="url(#arr-axis-chem)"/>
  <line x1="80" y1="310" x2="80" y2="60" stroke="#0f172a" stroke-width="2.5" marker-end="url(#arr-axis-chem)"/>
  <text x="520" y="335" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a">Reaction Progress</text>
  <text x="75" y="50" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Potential Energy</text>

  <!-- Reactants Level -->
  <line x1="80" y1="180" x2="180" y2="180" stroke="#0f172a" stroke-width="3"/>
  <text x="130" y="170" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">N₂ + 3H₂</text>

  <!-- Uncatalyzed Path (Red Peak) -->
  <path d="M 180 180 Q 280 40 380 250" fill="none" stroke="#dc2626" stroke-width="2.5"/>
  <text x="280" y="60" font-family="sans-serif" font-size="12" font-weight="bold" fill="#dc2626" text-anchor="middle">Uncatalyzed Ea</text>

  <!-- Catalyzed Path (Green Peak with Iron) -->
  <path d="M 180 180 Q 280 100 380 250" fill="none" stroke="#059669" stroke-width="2.5" stroke-dasharray="6,4"/>
  <text x="280" y="125" font-family="sans-serif" font-size="12" font-weight="bold" fill="#059669" text-anchor="middle">Catalyzed Ea (with Fe)</text>

  <!-- Products Level -->
  <line x1="380" y1="250" x2="480" y2="250" stroke="#0f172a" stroke-width="3"/>
  <text x="430" y="240" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">2NH₃</text>

  <!-- Enthalpy Change Delta H -->
  <line x1="390" y1="180" x2="470" y2="180" stroke="#64748b" stroke-width="1.5" stroke-dasharray="4,4"/>
  <line x1="450" y1="180" x2="450" y2="250" stroke="#2563eb" stroke-width="2"/>
  <text x="495" y="215" font-family="sans-serif" font-size="13" font-weight="bold" fill="#2563eb">ΔH = -92 kJ/mol</text>

  <text x="300" y="360" font-family="sans-serif" font-size="12" fill="#475569" text-anchor="middle">Catalyst lowers activation energy without altering the equilibrium position or enthalpy change.</text>
</svg>
''')

# 9. Math Q3: Circle Geometry Chord Bisector
diagrams['wq_waec_2023_math_p2_q3'] = save_svg('waec_math_2023_q3_circle_chord.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Circle Geometry: Perpendicular Bisector of Chord</text>

  <!-- Main Circle -->
  <circle cx="300" cy="190" r="130" fill="#ffffff" stroke="#0f172a" stroke-width="2.5"/>
  <circle cx="300" cy="190" r="4" fill="#0f172a"/>
  <text x="300" y="175" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">O (Center)</text>

  <!-- Chord AB -->
  <line x1="200" y1="270" x2="400" y2="270" stroke="#2563eb" stroke-width="3"/>
  <circle cx="200" cy="270" r="4" fill="#2563eb"/>
  <circle cx="400" cy="270" r="4" fill="#2563eb"/>
  <text x="185" y="275" font-family="sans-serif" font-size="14" font-weight="bold" fill="#2563eb">A</text>
  <text x="415" y="275" font-family="sans-serif" font-size="14" font-weight="bold" fill="#2563eb">B</text>

  <!-- Perpendicular bisector from O to Chord at D -->
  <line x1="300" y1="190" x2="300" y2="270" stroke="#dc2626" stroke-width="2.5"/>
  <circle cx="300" cy="270" r="4" fill="#dc2626"/>
  <text x="310" y="290" font-family="sans-serif" font-size="14" font-weight="bold" fill="#dc2626">D</text>

  <!-- Right angle marker -->
  <polyline points="290,270 290,260 300,260" fill="none" stroke="#dc2626" stroke-width="1.5"/>

  <!-- Radius OA -->
  <line x1="300" y1="190" x2="200" y2="270" stroke="#059669" stroke-width="2" stroke-dasharray="5,5"/>
  <text x="240" y="220" font-family="sans-serif" font-size="13" font-weight="bold" fill="#059669">r = 13 cm</text>

  <text x="300" y="350" font-family="sans-serif" font-size="13" fill="#0f172a" text-anchor="middle">Pythagoras Relation: OA² = OD² + AD²  |  Chord length AB = 24 cm, AD = 12 cm</text>
</svg>
''')

# 10. Math Q9: Composite Solid Toy (Cone on Hemisphere)
diagrams['wq_waec_2023_math_p2_q9'] = save_svg('waec_math_2023_q9_composite_toy.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Solid Composite Toy: Cone Mounted on Hemisphere</text>

  <!-- Cone vertex at top -->
  <polygon points="300,60 210,210 390,210" fill="#fed7aa" stroke="#c2410c" stroke-width="2.5"/>
  
  <!-- Common base ellipse -->
  <ellipse cx="300" cy="210" rx="90" ry="24" fill="#ffedd5" stroke="#c2410c" stroke-width="2"/>

  <!-- Hemisphere base -->
  <path d="M 210 210 A 90 90 0 0 0 390 210" fill="#fef08a" stroke="#ca8a04" stroke-width="2.5"/>

  <!-- Center and Radius -->
  <circle cx="300" cy="210" r="4" fill="#0f172a"/>
  <line x1="300" y1="210" x2="390" y2="210" stroke="#0f172a" stroke-width="2"/>
  <text x="345" y="200" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a">r = 7 cm</text>

  <!-- Cone Height h -->
  <line x1="300" y1="60" x2="300" y2="210" stroke="#2563eb" stroke-width="2" stroke-dasharray="4,4"/>
  <text x="270" y="140" font-family="sans-serif" font-size="14" font-weight="bold" fill="#2563eb">h = 24 cm</text>

  <!-- Slant height L -->
  <text x="370" y="130" font-family="sans-serif" font-size="14" font-weight="bold" fill="#c2410c">L = 25 cm</text>

  <text x="300" y="340" font-family="sans-serif" font-size="13" fill="#0f172a" text-anchor="middle">Composite Volume = Cone Volume (⅓πr²h) + Hemisphere Volume (⅔πr³)</text>
  <text x="300" y="360" font-family="sans-serif" font-size="12" fill="#64748b" text-anchor="middle">WAEC General Mathematics 2023 Paper 2 (SC4022 Q9)</text>
</svg>
''')

# 11. Math Q10: Mast Elevation
diagrams['wq_waec_2023_math_p2_q10'] = save_svg('waec_math_2023_q10_mast_elevation.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Angles of Elevation to Radio Mast</text>

  <!-- Ground line -->
  <line x1="80" y1="280" x2="520" y2="280" stroke="#0f172a" stroke-width="2.5"/>

  <!-- Vertical Mast TR -->
  <line x1="450" y1="280" x2="450" y2="80" stroke="#dc2626" stroke-width="3.5"/>
  <text x="450" y="70" font-family="sans-serif" font-size="14" font-weight="bold" fill="#dc2626" text-anchor="middle">T (Top of Mast)</text>
  <text x="450" y="300" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a" text-anchor="middle">R (Base)</text>
  <text x="465" y="180" font-family="sans-serif" font-size="14" font-weight="bold" fill="#dc2626">Height h</text>

  <!-- Post A -->
  <circle cx="150" cy="280" r="4" fill="#2563eb"/>
  <text x="150" y="305" font-family="sans-serif" font-size="14" font-weight="bold" fill="#2563eb" text-anchor="middle">Post A</text>
  <line x1="150" y1="280" x2="450" y2="80" stroke="#2563eb" stroke-width="2"/>
  <path d="M 200 280 A 50 50 0 0 0 195 250" fill="none" stroke="#2563eb" stroke-width="2"/>
  <text x="215" y="270" font-family="sans-serif" font-size="13" font-weight="bold" fill="#2563eb">32°</text>

  <!-- Post B -->
  <circle cx="310" cy="280" r="4" fill="#059669"/>
  <text x="310" y="305" font-family="sans-serif" font-size="14" font-weight="bold" fill="#059669" text-anchor="middle">Post B</text>
  <line x1="310" y1="280" x2="450" y2="80" stroke="#059669" stroke-width="2"/>
  <path d="M 350 280 A 40 40 0 0 0 340 240" fill="none" stroke="#059669" stroke-width="2"/>
  <text x="365" y="265" font-family="sans-serif" font-size="13" font-weight="bold" fill="#059669">58°</text>

  <!-- Distance between A and B -->
  <line x1="150" y1="330" x2="310" y2="330" stroke="#0f172a" stroke-width="1.5"/>
  <text x="230" y="350" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Distance AB = 50 m</text>
</svg>
''')

# 12. Math Q13: Navigation Bearings
diagrams['wq_waec_2023_math_p2_q13'] = save_svg('waec_math_2023_q13_bearings.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-north" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#0f172a"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Three-Figure Bearings Voyage Triangle (P, Q, R)</text>

  <!-- North lines -->
  <line x1="140" y1="260" x2="140" y2="180" stroke="#0f172a" stroke-width="2" marker-end="url(#arr-north)"/>
  <text x="140" y="170" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">N</text>

  <line x1="270" y1="185" x2="270" y2="105" stroke="#0f172a" stroke-width="2" marker-end="url(#arr-north)"/>
  <text x="270" y="95" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">N</text>

  <!-- Voyage legs -->
  <line x1="140" y1="260" x2="270" y2="185" stroke="#2563eb" stroke-width="3"/>
  <text x="195" y="215" font-family="sans-serif" font-size="13" font-weight="bold" fill="#2563eb">15 km (060°)</text>

  <line x1="270" y1="185" x2="443" y2="285" stroke="#059669" stroke-width="3"/>
  <text x="370" y="225" font-family="sans-serif" font-size="13" font-weight="bold" fill="#059669">20 km (150°)</text>

  <line x1="140" y1="260" x2="443" y2="285" stroke="#dc2626" stroke-width="2.5" stroke-dasharray="5,5"/>
  <text x="290" y="295" font-family="sans-serif" font-size="14" font-weight="bold" fill="#dc2626" text-anchor="middle">PR = 25 km</text>

  <!-- Port vertices -->
  <circle cx="140" cy="260" r="5" fill="#0f172a"/>
  <text x="125" y="275" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">P</text>
  <circle cx="270" cy="185" r="5" fill="#0f172a"/>
  <text x="285" y="180" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">Q</text>
  <circle cx="443" cy="285" r="5" fill="#0f172a"/>
  <text x="460" y="295" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">R</text>

  <text x="300" y="355" font-family="sans-serif" font-size="13" fill="#0f172a" text-anchor="middle">Interior Angle ∠PQR = 90°  ⟹  Pythagoras: PR² = 15² + 20² = 625  ⟹  PR = 25 km</text>
</svg>
''')

# 13. Biology Q4: Punnett Square
diagrams['wq_waec_2023_bio_p2_q4'] = save_svg('waec_bio_2023_q4_punnett.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Mendelian Monohybrid Cross (Punnett Square F₂ Generation)</text>

  <!-- Parents -->
  <text x="300" y="70" font-family="sans-serif" font-size="14" font-weight="bold" fill="#1e3a8a" text-anchor="middle">F₁ Parents: Heterozygous Tall (Tt) × Heterozygous Tall (Tt)</text>

  <!-- Punnett Grid -->
  <rect x="200" y="100" width="200" height="200" fill="#ffffff" stroke="#0f172a" stroke-width="2.5"/>
  <line x1="300" y1="100" x2="300" y2="300" stroke="#0f172a" stroke-width="2"/>
  <line x1="200" y1="200" x2="400" y2="200" stroke="#0f172a" stroke-width="2"/>

  <!-- Gamete labels outside -->
  <circle cx="250" cy="80" r="14" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="250" y="85" font-family="sans-serif" font-size="14" font-weight="bold" fill="#1e40af" text-anchor="middle">T</text>
  <circle cx="350" cy="80" r="14" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="350" y="85" font-family="sans-serif" font-size="14" font-weight="bold" fill="#1e40af" text-anchor="middle">t</text>

  <circle cx="170" cy="150" r="14" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="170" y="155" font-family="sans-serif" font-size="14" font-weight="bold" fill="#1e40af" text-anchor="middle">T</text>
  <circle cx="170" cy="250" r="14" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="170" y="255" font-family="sans-serif" font-size="14" font-weight="bold" fill="#1e40af" text-anchor="middle">t</text>

  <!-- Cell contents -->
  <text x="250" y="145" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">TT</text>
  <text x="250" y="165" font-family="sans-serif" font-size="11" fill="#16a34a" text-anchor="middle">(Homozygous Tall)</text>

  <text x="350" y="145" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Tt</text>
  <text x="350" y="165" font-family="sans-serif" font-size="11" fill="#16a34a" text-anchor="middle">(Heterozygous Tall)</text>

  <text x="250" y="245" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Tt</text>
  <text x="250" y="265" font-family="sans-serif" font-size="11" fill="#16a34a" text-anchor="middle">(Heterozygous Tall)</text>

  <text x="350" y="245" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">tt</text>
  <text x="350" y="265" font-family="sans-serif" font-size="11" fill="#dc2626" text-anchor="middle">(Dwarf)</text>

  <text x="300" y="340" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Phenotypic Ratio: 3 Tall : 1 Dwarf  |  Genotypic Ratio: 1 TT : 2 Tt : 1 tt</text>
</svg>
''')

# 14. Agriculture Q3: Soil Profile
diagrams['wq_waec_2023_agr_p2_q3'] = save_svg('waec_agr_2023_q3_soil_profile.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Soil Profile: Master Pedological Horizons</text>

  <!-- Soil Column -->
  <rect x="150" y="60" width="160" height="260" fill="none" stroke="#0f172a" stroke-width="2.5"/>

  <!-- Horizon O (Organic) -->
  <rect x="150" y="60" width="160" height="35" fill="#451a03"/>
  <text x="230" y="82" font-family="sans-serif" font-size="12" font-weight="bold" fill="#ffffff" text-anchor="middle">Horizon O</text>

  <!-- Horizon A (Topsoil) -->
  <rect x="150" y="95" width="160" height="65" fill="#78350f"/>
  <text x="230" y="132" font-family="sans-serif" font-size="12" font-weight="bold" fill="#ffffff" text-anchor="middle">Horizon A (Topsoil)</text>

  <!-- Horizon B (Subsoil) -->
  <rect x="150" y="160" width="160" height="85" fill="#b45309"/>
  <text x="230" y="207" font-family="sans-serif" font-size="12" font-weight="bold" fill="#ffffff" text-anchor="middle">Horizon B (Subsoil)</text>

  <!-- Horizon C (Weathered Rock) -->
  <rect x="150" y="245" width="160" height="75" fill="#d97706"/>
  <text x="230" y="287" font-family="sans-serif" font-size="12" font-weight="bold" fill="#ffffff" text-anchor="middle">Horizon C (Parent Material)</text>

  <!-- Horizon annotations -->
  <text x="340" y="82" font-family="sans-serif" font-size="13" font-weight="bold" fill="#451a03">Horizon O: Organic litter and fresh humus</text>
  <text x="340" y="132" font-family="sans-serif" font-size="13" font-weight="bold" fill="#78350f">Horizon A: Dark topsoil rich in decayed humus</text>
  <text x="340" y="207" font-family="sans-serif" font-size="13" font-weight="bold" fill="#b45309">Horizon B: Mineral accumulation zone (clay, Fe/Al)</text>
  <text x="340" y="287" font-family="sans-serif" font-size="13" font-weight="bold" fill="#d97706">Horizon C: Partially weathered bedrock</text>

  <text x="300" y="355" font-family="sans-serif" font-size="12" fill="#64748b" text-anchor="middle">WAEC Agricultural Science 2023 Paper 2 (SC5032 Q3)</text>
</svg>
''')

print(f"Generated {len(diagrams)} SVG vector diagrams!")

# Update reference json with diagram URLs
with open('data/theory/waec_theory_reference.json') as f:
    items = json.load(f)

updated_count = 0
for q in items:
    qid = q['id']
    if qid in diagrams:
        q['diagram_url'] = diagrams[qid]
        updated_count += 1

with open('data/theory/waec_theory_reference.json', 'w') as f:
    json.dump(items, f, indent=2)

print(f"Successfully linked {updated_count} questions to their vector SVG diagrams in waec_theory_reference.json!")

# 15. Chemistry Q2: Titration Setup
diagrams['wq_waec_2023_chem_p2_q2'] = save_svg('waec_chem_2023_q2_titration.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Acid - Base Neutralization Titration Setup</text>

  <!-- Retort stand -->
  <rect x="140" y="320" width="120" height="15" fill="#334155" rx="2"/>
  <line x1="160" y1="320" x2="160" y2="60" stroke="#475569" stroke-width="5"/>
  <line x1="160" y1="120" x2="250" y2="120" stroke="#475569" stroke-width="3"/>
  <circle cx="250" cy="120" r="8" fill="#64748b"/>

  <!-- Burette -->
  <rect x="245" y="60" width="10" height="180" fill="#e0f2fe" stroke="#0284c7" stroke-width="1.5"/>
  <polygon points="247,240 253,240 250,255" fill="#0284c7"/>
  <circle cx="250" cy="245" r="4" fill="#0f172a"/>
  <!-- Burette volume level -->
  <rect x="246" y="100" width="8" height="140" fill="#bae6fd"/>
  <text x="270" y="90" font-family="sans-serif" font-size="12" font-weight="bold" fill="#0369a1">Burette with dilute H₂SO₄</text>
  <text x="270" y="110" font-family="sans-serif" font-size="11" fill="#0284c7">Titre volume = 8.0 cm³</text>

  <!-- Conical Flask -->
  <polygon points="230,265 270,265 295,320 205,320" fill="#dcfce7" stroke="#15803d" stroke-width="2"/>
  <rect x="240" y="255" width="20" height="12" fill="#dcfce7" stroke="#15803d" stroke-width="1.5"/>
  <text x="320" y="285" font-family="sans-serif" font-size="12" font-weight="bold" fill="#15803d">Conical Flask</text>
  <text x="320" y="305" font-family="sans-serif" font-size="11" fill="#166534">20.0 cm³ 4.0 g/dm³ NaOH (aq)</text>
  <text x="320" y="320" font-family="sans-serif" font-size="11" fill="#166534">+ Indicator</text>

  <text x="300" y="360" font-family="sans-serif" font-size="12" fill="#0f172a" text-anchor="middle">Reaction: 2NaOH(aq) + H₂SO₄(aq) ⟶ Na₂SO₄(aq) + 2H₂O(l)  |  Ca = 0.125 mol dm⁻³</text>
</svg>
''')

# 16. Chemistry Q5: Electrolysis Cell
diagrams['wq_waec_2023_chem_p2_q5'] = save_svg('waec_chem_2023_q5_electrolysis_cell.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Electrolysis of Aqueous Copper(II) Tetraoxosulphate(VI)</text>

  <!-- Electrolytic tank -->
  <rect x="130" y="100" width="340" height="190" fill="#dbeafe" stroke="#0f172a" stroke-width="2.5" rx="4"/>
  <text x="300" y="275" font-family="sans-serif" font-size="13" font-weight="bold" fill="#1e40af" text-anchor="middle">Aqueous CuSO₄ Solution</text>

  <!-- Anode (Copper) -->
  <rect x="190" y="80" width="25" height="170" fill="#ea580c" stroke="#9a3412" stroke-width="2"/>
  <text x="202" y="70" font-family="sans-serif" font-size="13" font-weight="bold" fill="#9a3412" text-anchor="middle">Anode (+)</text>
  <text x="202" y="170" font-family="sans-serif" font-size="11" fill="#ffffff" text-anchor="middle">Cu</text>

  <!-- Cathode (Copper) -->
  <rect x="385" y="80" width="25" height="170" fill="#b45309" stroke="#78350f" stroke-width="2"/>
  <text x="397" y="70" font-family="sans-serif" font-size="13" font-weight="bold" fill="#78350f" text-anchor="middle">Cathode (-)</text>
  <text x="397" y="170" font-family="sans-serif" font-size="11" fill="#ffffff" text-anchor="middle">Cu Deposit</text>

  <!-- Circuit with Battery and Ammeter -->
  <polyline points="202,80 202,50 260,50" fill="none" stroke="#0f172a" stroke-width="2"/>
  <line x1="260" y1="40" x2="260" y2="60" stroke="#0f172a" stroke-width="3"/>
  <line x1="270" y1="45" x2="270" y2="55" stroke="#0f172a" stroke-width="2"/>
  <line x1="270" y1="50" x2="330" y2="50" stroke="#0f172a" stroke-width="2"/>
  <!-- Ammeter -->
  <circle cx="350" cy="50" r="14" fill="#ffffff" stroke="#0f172a" stroke-width="2"/>
  <text x="350" y="55" font-family="sans-serif" font-size="12" font-weight="bold" fill="#0f172a" text-anchor="middle">A</text>
  <polyline points="364,50 397,50 397,80" fill="none" stroke="#0f172a" stroke-width="2"/>

  <text x="300" y="325" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Current I = 2.50 A, Time t = 35 minutes  |  Mass Deposited = 1.73 g</text>
  <text x="300" y="355" font-family="sans-serif" font-size="12" fill="#475569" text-anchor="middle">Cathode Half-Reaction: Cu²⁺(aq) + 2e⁻ ⟶ Cu(s)  [z = 2]</text>
</svg>
''')

# 17. Physics Q7: Optical Fiber Total Internal Reflection
diagrams['wq_waec_2023_phys_p2_q7'] = save_svg('waec_phys_2023_q7_optical_fiber.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-ray" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#dc2626"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Total Internal Reflection in Optical Fibre</text>

  <!-- Cladding top -->
  <rect x="80" y="100" width="440" height="35" fill="#e2e8f0" stroke="#94a3b8" stroke-width="1.5"/>
  <text x="300" y="122" font-family="sans-serif" font-size="12" font-weight="bold" fill="#475569" text-anchor="middle">Cladding (Lower Refractive Index n₂)</text>

  <!-- Core -->
  <rect x="80" y="135" width="440" height="110" fill="#eff6ff" stroke="#2563eb" stroke-width="2"/>
  <text x="300" y="195" font-family="sans-serif" font-size="14" font-weight="bold" fill="#1e40af" text-anchor="middle">Dense Core (Higher Refractive Index n₁)</text>

  <!-- Cladding bottom -->
  <rect x="80" y="245" width="440" height="35" fill="#e2e8f0" stroke="#94a3b8" stroke-width="1.5"/>
  <text x="300" y="267" font-family="sans-serif" font-size="12" font-weight="bold" fill="#475569" text-anchor="middle">Cladding (Lower Refractive Index n₂)</text>

  <!-- Zig-zag light ray with TIR -->
  <polyline points="40,210 130,135 250,245 370,135 490,245 560,180" fill="none" stroke="#dc2626" stroke-width="3" marker-mid="url(#arr-ray)"/>

  <!-- Angle of incidence -->
  <line x1="250" y1="210" x2="250" y2="270" stroke="#64748b" stroke-width="1.5" stroke-dasharray="3,3"/>
  <text x="260" y="235" font-family="sans-serif" font-size="12" font-weight="bold" fill="#dc2626">θ &gt; θ_c</text>

  <text x="300" y="325" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Conditions: n₁ &gt; n₂ and Angle of Incidence &gt; Critical Angle</text>
  <text x="300" y="350" font-family="sans-serif" font-size="12" fill="#475569" text-anchor="middle">Advantages over copper: Higher bandwidth, immunity to electromagnetic interference</text>
</svg>
''')

# 18. Physics Q12: Bridge Rectifier Schematic
diagrams['wq_waec_2023_phys_p2_q12'] = save_svg('waec_phys_2023_q12_bridge_rectifier.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Full-Wave Bridge Rectifier with Smoothing Capacitor</text>

  <!-- AC Input -->
  <circle cx="100" cy="180" r="22" fill="#ffffff" stroke="#0f172a" stroke-width="2"/>
  <path d="M 90 180 Q 95 170 100 180 T 110 180" fill="none" stroke="#0f172a" stroke-width="2"/>
  <text x="100" y="220" font-family="sans-serif" font-size="12" font-weight="bold" fill="#0f172a" text-anchor="middle">AC Input</text>

  <!-- Bridge Diamond -->
  <polyline points="100,158 100,120 250,120 250,140" fill="none" stroke="#0f172a" stroke-width="2"/>
  <polyline points="100,202 100,240 250,240 250,220" fill="none" stroke="#0f172a" stroke-width="2"/>

  <polygon points="250,130 330,180 250,230 170,180" fill="none" stroke="#334155" stroke-width="2"/>

  <!-- Diode labels on bridge arms -->
  <text x="200" y="145" font-family="sans-serif" font-size="12" font-weight="bold" fill="#2563eb">D₁</text>
  <text x="300" y="145" font-family="sans-serif" font-size="12" font-weight="bold" fill="#2563eb">D₂</text>
  <text x="200" y="220" font-family="sans-serif" font-size="12" font-weight="bold" fill="#2563eb">D₄</text>
  <text x="300" y="220" font-family="sans-serif" font-size="12" font-weight="bold" fill="#2563eb">D₃</text>

  <!-- DC output connections -->
  <line x1="250" y1="130" x2="480" y2="130" stroke="#0f172a" stroke-width="2"/>
  <line x1="250" y1="230" x2="480" y2="230" stroke="#0f172a" stroke-width="2"/>
  <text x="490" y="135" font-family="sans-serif" font-size="14" font-weight="bold" fill="#dc2626">+</text>
  <text x="490" y="235" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">-</text>

  <!-- Smoothing Capacitor C -->
  <line x1="390" y1="130" x2="390" y2="170" stroke="#0f172a" stroke-width="2"/>
  <line x1="375" y1="170" x2="405" y2="170" stroke="#0f172a" stroke-width="3"/>
  <line x1="375" y1="180" x2="405" y2="180" stroke="#0f172a" stroke-width="3"/>
  <line x1="390" y1="180" x2="390" y2="230" stroke="#0f172a" stroke-width="2"/>
  <text x="415" y="180" font-family="sans-serif" font-size="12" font-weight="bold" fill="#059669">Filter C</text>

  <!-- Load Resistor RL -->
  <rect x="450" y="155" width="20" height="50" fill="#ffffff" stroke="#0f172a" stroke-width="2"/>
  <line x1="460" y1="130" x2="460" y2="155" stroke="#0f172a" stroke-width="2"/>
  <line x1="460" y1="205" x2="460" y2="230" stroke="#0f172a" stroke-width="2"/>
  <text x="480" y="185" font-family="sans-serif" font-size="12" font-weight="bold" fill="#0f172a">R_L</text>

  <text x="300" y="325" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Conduction: D₁, D₃ on positive half-cycle; D₂, D₄ on negative half-cycle</text>
  <text x="300" y="350" font-family="sans-serif" font-size="12" fill="#475569" text-anchor="middle">Capacitor C discharges slowly across R_L, eliminating voltage ripples for steady DC</text>
</svg>
''')

# 19. Math Q1: Venn Diagram
diagrams['wq_waec_2023_math_p2_q1'] = save_svg('waec_math_2023_q1_venn.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Two-Set Venn Diagram (Universal Set U = 45)</text>

  <!-- Universal set rectangle -->
  <rect x="80" y="60" width="440" height="260" fill="#ffffff" stroke="#0f172a" stroke-width="2.5" rx="6"/>
  <text x="100" y="85" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">ξ = 45</text>

  <!-- Set M (Mathematics) -->
  <circle cx="240" cy="180" r="85" fill="#dbeafe" fill-opacity="0.6" stroke="#2563eb" stroke-width="2.5"/>
  <text x="180" y="125" font-family="sans-serif" font-size="14" font-weight="bold" fill="#1e40af">M (28)</text>

  <!-- Set E (English) -->
  <circle cx="360" cy="180" r="85" fill="#fef08a" fill-opacity="0.6" stroke="#ca8a04" stroke-width="2.5"/>
  <text x="400" y="125" font-family="sans-serif" font-size="14" font-weight="bold" fill="#854d0e">E (20)</text>

  <!-- Region counts -->
  <text x="210" y="185" font-family="sans-serif" font-size="15" font-weight="bold" fill="#1e40af" text-anchor="middle">28 - x</text>
  <text x="210" y="205" font-family="sans-serif" font-size="12" fill="#1e40af" text-anchor="middle">(17)</text>

  <text x="300" y="185" font-family="sans-serif" font-size="16" font-weight="bold" fill="#dc2626" text-anchor="middle">x</text>
  <text x="300" y="205" font-family="sans-serif" font-size="12" fill="#dc2626" text-anchor="middle">(x = 11)</text>

  <text x="390" y="185" font-family="sans-serif" font-size="15" font-weight="bold" fill="#854d0e" text-anchor="middle">20 - x</text>
  <text x="390" y="205" font-family="sans-serif" font-size="12" fill="#854d0e" text-anchor="middle">(9)</text>

  <!-- Outside neither -->
  <text x="470" y="290" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">8</text>
  <text x="460" y="305" font-family="sans-serif" font-size="11" fill="#64748b">(Neither)</text>

  <text x="300" y="355" font-family="sans-serif" font-size="13" fill="#0f172a" text-anchor="middle">Equation: (28 - x) + x + (20 - x) + 8 = 45  ⟹  56 - x = 45  ⟹  x = 11</text>
</svg>
''')

# 20. Math Q11: Circle Theorem Cyclic Quad
diagrams['wq_waec_2023_math_p2_q11'] = save_svg('waec_math_2023_q11_circle_theorems.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Circle Theorems: Cyclic Quadrilateral and Angles at Centre</text>

  <!-- Circle -->
  <circle cx="300" cy="180" r="120" fill="#ffffff" stroke="#0f172a" stroke-width="2.5"/>
  <circle cx="300" cy="180" r="4" fill="#0f172a"/>
  <text x="290" y="175" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a">O</text>

  <!-- Cyclic Quad PQRS -->
  <polygon points="210,120 380,100 405,240 230,265" fill="#eff6ff" stroke="#2563eb" stroke-width="2.5"/>
  <circle cx="210" cy="120" r="4" fill="#2563eb"/>
  <text x="195" y="115" font-family="sans-serif" font-size="14" font-weight="bold" fill="#2563eb">P</text>
  <circle cx="380" cy="100" r="4" fill="#2563eb"/>
  <text x="390" y="95" font-family="sans-serif" font-size="14" font-weight="bold" fill="#2563eb">Q</text>
  <circle cx="405" cy="240" r="4" fill="#2563eb"/>
  <text x="420" y="245" font-family="sans-serif" font-size="14" font-weight="bold" fill="#2563eb">R</text>
  <circle cx="230" cy="265" r="4" fill="#2563eb"/>
  <text x="215" y="280" font-family="sans-serif" font-size="14" font-weight="bold" fill="#2563eb">S</text>

  <!-- Tangent line at S -->
  <line x1="160" y1="285" x2="310" y2="245" stroke="#dc2626" stroke-width="2"/>
  <text x="150" y="305" font-family="sans-serif" font-size="12" font-weight="bold" fill="#dc2626">Tangent</text>

  <text x="300" y="345" font-family="sans-serif" font-size="13" fill="#0f172a" text-anchor="middle">Opposite angles of cyclic quadrilateral are supplementary: ∠P + ∠R = 180°</text>
</svg>
''')

# Update reference json with all diagrams
with open('data/theory/waec_theory_reference.json') as f:
    items = json.load(f)

updated_count = 0
for q in items:
    qid = q['id']
    if qid in diagrams:
        q['diagram_url'] = diagrams[qid]
        updated_count += 1

with open('data/theory/waec_theory_reference.json', 'w') as f:
    json.dump(items, f, indent=2)

print(f"Total diagrams registered: {len(diagrams)}")
print(f"Total questions with diagram_url now in JSON: {updated_count}")

# 21. Math Q4: Rectangular Garden Plot
diagrams['wq_waec_2023_math_p2_q4'] = save_svg('waec_math_2023_q4_garden.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="35" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Rectangular Vegetable Garden (Perimeter and Area Constraints)</text>

  <!-- Garden rectangle -->
  <rect x="130" y="100" width="340" height="170" fill="#ecfdf5" stroke="#059669" stroke-width="3" rx="4"/>
  <text x="300" y="180" font-family="sans-serif" font-size="16" font-weight="bold" fill="#065f46" text-anchor="middle">Area = 135 m²</text>
  <text x="300" y="205" font-family="sans-serif" font-size="13" fill="#047857" text-anchor="middle">L × B = 135</text>

  <!-- Dimensions -->
  <line x1="130" y1="80" x2="470" y2="80" stroke="#0f172a" stroke-width="1.5"/>
  <text x="300" y="70" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a" text-anchor="middle">Length L = 15 m</text>

  <line x1="110" y1="100" x2="110" y2="270" stroke="#0f172a" stroke-width="1.5"/>
  <text x="80" y="190" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a" text-anchor="middle">B = 9 m</text>

  <text x="300" y="325" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Perimeter: 2(L + B) = 48  ⟹  L + B = 24  ⟹  B = 24 - L</text>
  <text x="300" y="350" font-family="sans-serif" font-size="13" fill="#2563eb" text-anchor="middle">Quadratic Formulation: L² - 24L + 135 = 0  ⟹  (L - 15)(L - 9) = 0</text>
</svg>
''')

# 22. Math Q8: Quadratic Parabola Graph
diagrams['wq_waec_2023_math_p2_q8'] = save_svg('waec_math_2023_q8_parabola.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-g" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#0f172a"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Quadratic Graph: y = 2x² - 3x - 5</text>

  <!-- Axes -->
  <line x1="80" y1="200" x2="520" y2="200" stroke="#0f172a" stroke-width="2" marker-end="url(#arr-g)"/>
  <line x1="260" y1="330" x2="260" y2="50" stroke="#0f172a" stroke-width="2" marker-end="url(#arr-g)"/>
  <text x="530" y="205" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a">x</text>
  <text x="255" y="45" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a">y</text>

  <!-- Parabola Curve -->
  <path d="M 120 70 Q 295 350 470 70" fill="none" stroke="#2563eb" stroke-width="3"/>

  <!-- Roots at y = 0: x = -1 (x=200) and x = 2.5 (x=410) -->
  <circle cx="200" cy="200" r="5" fill="#dc2626"/>
  <text x="185" y="190" font-family="sans-serif" font-size="12" font-weight="bold" fill="#dc2626">x = -1</text>
  <circle cx="410" cy="200" r="5" fill="#dc2626"/>
  <text x="425" y="190" font-family="sans-serif" font-size="12" font-weight="bold" fill="#dc2626">x = 2.5</text>

  <!-- Vertex / Minimum point (0.75, -6.125) (x=295, y=280) -->
  <circle cx="295" cy="280" r="5" fill="#059669"/>
  <text x="315" y="295" font-family="sans-serif" font-size="12" font-weight="bold" fill="#059669">Vertex (0.75, -6.125)</text>

  <!-- Axis of Symmetry x = 0.75 -->
  <line x1="295" y1="60" x2="295" y2="310" stroke="#059669" stroke-width="1.5" stroke-dasharray="4,4"/>
  <text x="295" y="325" font-family="sans-serif" font-size="12" fill="#059669" text-anchor="middle">Line of Symmetry: x = 0.75</text>
</svg>
''')

# 23. Math Q12: Cumulative Frequency Ogive
diagrams['wq_waec_2023_math_p2_q12'] = save_svg('waec_math_2023_q12_ogive.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-ogive" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#0f172a"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Cumulative Frequency Curve (Ogive)</text>

  <!-- Grid lines -->
  <line x1="100" y1="290" x2="520" y2="290" stroke="#0f172a" stroke-width="2" marker-end="url(#arr-ogive)"/>
  <line x1="100" y1="290" x2="100" y2="60" stroke="#0f172a" stroke-width="2" marker-end="url(#arr-ogive)"/>
  <text x="530" y="295" font-family="sans-serif" font-size="12" font-weight="bold" fill="#0f172a">Marks (Upper Boundaries)</text>
  <text x="95" y="45" font-family="sans-serif" font-size="12" font-weight="bold" fill="#0f172a" text-anchor="middle">Cumulative Frequency</text>

  <!-- S-shaped Ogive curve -->
  <path d="M 120 290 Q 250 280 290 190 T 480 80" fill="none" stroke="#2563eb" stroke-width="3"/>

  <!-- Median at CF = 25 (y = 185) -->
  <line x1="100" y1="185" x2="290" y2="185" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4,4"/>
  <line x1="290" y1="185" x2="290" y2="290" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4,4"/>
  <circle cx="290" cy="185" r="4" fill="#dc2626"/>
  <text x="65" y="190" font-family="sans-serif" font-size="12" font-weight="bold" fill="#dc2626">CF = 25</text>
  <text x="290" y="310" font-family="sans-serif" font-size="12" font-weight="bold" fill="#dc2626" text-anchor="middle">Median = 49.5</text>

  <!-- Quartiles Q1 and Q3 -->
  <text x="300" y="350" font-family="sans-serif" font-size="12" fill="#0f172a" text-anchor="middle">Semi-Interquartile Range = ½ (Q₃ - Q₁) = ½ (60.5 - 38.5) = 11.0 marks</text>
</svg>
''')

# 24. Physics Q9: Parabolic Mirror and Echo
diagrams['wq_waec_2023_phys_p2_q9'] = save_svg('waec_phys_2023_q9_parabolic_mirror.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-m" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Parabolic Mirror Headlamp Beam (Eliminating Spherical Aberration)</text>

  <!-- Parabolic curve mirror -->
  <path d="M 160 80 Q 260 180 160 280" fill="none" stroke="#0f172a" stroke-width="4"/>

  <!-- Principal Axis -->
  <line x1="120" y1="180" x2="520" y2="180" stroke="#64748b" stroke-width="1.5" stroke-dasharray="6,4"/>

  <!-- Bulb at Focus F -->
  <circle cx="215" cy="180" r="7" fill="#facc15" stroke="#ca8a04" stroke-width="2"/>
  <text x="215" y="165" font-family="sans-serif" font-size="12" font-weight="bold" fill="#ca8a04" text-anchor="middle">Lamp Focus (F)</text>

  <!-- Rays from focus reflecting parallel -->
  <line x1="215" y1="180" x2="175" y2="105" stroke="#2563eb" stroke-width="2"/>
  <line x1="175" y1="105" x2="500" y2="105" stroke="#2563eb" stroke-width="2" marker-end="url(#arr-m)"/>

  <line x1="215" y1="180" x2="235" y2="180" stroke="#2563eb" stroke-width="2"/>
  <line x1="235" y1="180" x2="500" y2="180" stroke="#2563eb" stroke-width="2" marker-end="url(#arr-m)"/>

  <line x1="215" y1="180" x2="175" y2="255" stroke="#2563eb" stroke-width="2"/>
  <line x1="175" y1="255" x2="500" y2="255" stroke="#2563eb" stroke-width="2" marker-end="url(#arr-m)"/>

  <text x="350" y="95" font-family="sans-serif" font-size="13" font-weight="bold" fill="#2563eb">Parallel Reflected Beam</text>

  <text x="300" y="330" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Echo Sounding: Depth d = (v · t) / 2 = (1500 × 0.80) / 2 = 600 m</text>
  <text x="300" y="355" font-family="sans-serif" font-size="12" fill="#475569" text-anchor="middle">Ultrasonic Wavelength: λ = v / f = 1500 / 50000 = 0.030 m (3.0 cm)</text>
</svg>
''')

# 25. Physics Q10: Immersion Calorimetry
diagrams['wq_waec_2023_phys_p2_q10'] = save_svg('waec_phys_2023_q10_calorimeter.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Electric Immersion Heating Calorimetry Setup</text>

  <!-- Outer Lagging Jacket -->
  <rect x="170" y="100" width="260" height="190" fill="#f1f5f9" stroke="#64748b" stroke-width="2.5" rx="6"/>
  <text x="440" y="200" font-family="sans-serif" font-size="12" fill="#64748b">Insulating Lagging</text>

  <!-- Copper Calorimeter -->
  <rect x="200" y="120" width="200" height="160" fill="#fed7aa" stroke="#c2410c" stroke-width="2" rx="4"/>
  <text x="130" y="240" font-family="sans-serif" font-size="12" font-weight="bold" fill="#c2410c">Copper Calorimeter (0.20 kg)</text>

  <!-- Water inside -->
  <rect x="202" y="160" width="196" height="118" fill="#bae6fd" fill-opacity="0.8"/>
  <text x="300" y="250" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0369a1" text-anchor="middle">Water (0.80 kg)</text>

  <!-- Immersion Heater -->
  <rect x="285" y="80" width="30" height="160" fill="#334155" rx="3"/>
  <text x="300" y="70" font-family="sans-serif" font-size="12" font-weight="bold" fill="#0f172a" text-anchor="middle">Immersion Heater (600 W)</text>

  <!-- Stirrer -->
  <path d="M 235 90 L 235 260 L 255 260" fill="none" stroke="#475569" stroke-width="2.5"/>
  <text x="235" y="80" font-family="sans-serif" font-size="11" fill="#475569" text-anchor="middle">Stirrer</text>

  <!-- Thermometer -->
  <rect x="350" y="80" width="8" height="170" fill="#fee2e2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="354" y="70" font-family="sans-serif" font-size="11" fill="#dc2626" text-anchor="middle">Thermometer</text>

  <text x="300" y="325" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Heat Supplied = Heat Gained by Water and Copper Vessel</text>
  <text x="300" y="350" font-family="sans-serif" font-size="12" fill="#475569" text-anchor="middle">P · t = (m_w · c_w + m_c · c_c) · Δθ + m_v · L_v</text>
</svg>
''')

# 26. Physics Q11: Electric Field Point Charges
diagrams['wq_waec_2023_phys_p2_q11'] = save_svg('waec_phys_2023_q11_electric_field.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-field" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#dc2626"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Electric Field Superposition Between Point Charges</text>

  <!-- Charge q1 (+4.0 uC) -->
  <circle cx="150" cy="180" r="28" fill="#dbeafe" stroke="#2563eb" stroke-width="3"/>
  <text x="150" y="186" font-family="sans-serif" font-size="20" font-weight="bold" fill="#1e40af" text-anchor="middle">+</text>
  <text x="150" y="225" font-family="sans-serif" font-size="13" font-weight="bold" fill="#1e40af" text-anchor="middle">q₁ = +4.0 μC</text>

  <!-- Charge q2 (-2.0 uC) -->
  <circle cx="450" cy="180" r="24" fill="#fee2e2" stroke="#dc2626" stroke-width="3"/>
  <text x="450" y="186" font-family="sans-serif" font-size="22" font-weight="bold" fill="#991b1b" text-anchor="middle">-</text>
  <text x="450" y="225" font-family="sans-serif" font-size="13" font-weight="bold" fill="#991b1b" text-anchor="middle">q₂ = -2.0 μC</text>

  <!-- Separation distance -->
  <line x1="150" y1="180" x2="450" y2="180" stroke="#64748b" stroke-width="1.5" stroke-dasharray="5,5"/>
  <text x="300" y="140" font-family="sans-serif" font-size="13" fill="#64748b" text-anchor="middle">Distance d = 0.20 m</text>

  <!-- Midpoint M -->
  <circle cx="300" cy="180" r="6" fill="#059669"/>
  <text x="300" y="165" font-family="sans-serif" font-size="13" font-weight="bold" fill="#059669" text-anchor="middle">Midpoint (r = 0.10 m)</text>

  <!-- Field Vectors E1 and E2 at Midpoint both pointing right -->
  <line x1="300" y1="180" x2="380" y2="180" stroke="#2563eb" stroke-width="3" marker-end="url(#arr-field)"/>
  <text x="340" y="200" font-family="sans-serif" font-size="12" font-weight="bold" fill="#2563eb">E₁ (away from +)</text>

  <line x1="300" y1="180" x2="350" y2="180" stroke="#dc2626" stroke-width="2.5" marker-end="url(#arr-field)"/>
  <text x="340" y="220" font-family="sans-serif" font-size="12" font-weight="bold" fill="#dc2626">E₂ (towards -)</text>

  <text x="300" y="325" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Net Field: E_net = E₁ + E₂ = 3.6×10⁶ + 1.8×10⁶ = 5.4×10⁶ N/C (toward q₂)</text>
  <text x="300" y="350" font-family="sans-serif" font-size="12" fill="#475569" text-anchor="middle">Force on electron: F = e · E_net = (1.6×10⁻¹⁹) × (5.4×10⁶) = 8.64×10⁻¹³ N</text>
</svg>
''')

# 27. Chemistry Q3: Volumetric Analysis Apparatus
diagrams['wq_waec_2023_chem_p2_q3'] = save_svg('waec_chem_2023_q3_volumetric.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Volumetric Analysis: Standardization of H₂SO₄ against Na₂CO₃</text>

  <!-- Apparatus setup -->
  <line x1="180" y1="320" x2="180" y2="60" stroke="#475569" stroke-width="5"/>
  <rect x="150" y="320" width="100" height="15" fill="#334155" rx="2"/>

  <!-- Burette with Acid -->
  <rect x="250" y="60" width="12" height="190" fill="#e0f2fe" stroke="#0284c7" stroke-width="1.5"/>
  <text x="280" y="110" font-family="sans-serif" font-size="12" font-weight="bold" fill="#0369a1">Burette: H₂SO₄</text>
  <text x="280" y="130" font-family="sans-serif" font-size="11" fill="#0284c7">Average titre = 24.50 cm³</text>

  <!-- Conical Flask with Standard Base -->
  <polygon points="235,270 275,270 300,320 210,320" fill="#fef08a" stroke="#ca8a04" stroke-width="2"/>
  <text x="320" y="285" font-family="sans-serif" font-size="12" font-weight="bold" fill="#854d0e">Conical Flask</text>
  <text x="320" y="305" font-family="sans-serif" font-size="11" fill="#854d0e">25.0 cm³ of 0.050 mol dm⁻³ Na₂CO₃</text>
  <text x="320" y="320" font-family="sans-serif" font-size="11" fill="#dc2626">+ Methyl Orange Indicator</text>

  <text x="300" y="355" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Equation: Na₂CO₃(aq) + H₂SO₄(aq) ⟶ Na₂SO₄(aq) + H₂O(l) + CO₂(g)</text>
</svg>
''')

# 28. Chemistry Q6: Fermentation Flow Chart
diagrams['wq_waec_2023_chem_p2_q6'] = save_svg('waec_chem_2023_q6_fermentation.svg', '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">
  <defs>
    <marker id="arr-flow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc" rx="8"/>
  <text x="300" y="30" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a" text-anchor="middle">Enzymatic Fermentation of Cassava Starch to Ethanol</text>

  <!-- Step 1: Starch -->
  <rect x="50" y="80" width="130" height="60" fill="#fef3c7" stroke="#d97706" stroke-width="2" rx="4"/>
  <text x="115" y="105" font-family="sans-serif" font-size="13" font-weight="bold" fill="#92400e" text-anchor="middle">Cassava Starch</text>
  <text x="115" y="125" font-family="sans-serif" font-size="11" fill="#78350f" text-anchor="middle">(C₆H₁₀O₅)_n</text>

  <line x1="180" y1="110" x2="230" y2="110" stroke="#2563eb" stroke-width="2.5" marker-end="url(#arr-flow)"/>
  <text x="205" y="95" font-family="sans-serif" font-size="11" font-weight="bold" fill="#2563eb" text-anchor="middle">Diastase (Malt)</text>

  <!-- Step 2: Maltose -->
  <rect x="230" y="80" width="130" height="60" fill="#dbeafe" stroke="#2563eb" stroke-width="2" rx="4"/>
  <text x="295" y="105" font-family="sans-serif" font-size="13" font-weight="bold" fill="#1e40af" text-anchor="middle">Maltose</text>
  <text x="295" y="125" font-family="sans-serif" font-size="11" fill="#1e3a8a" text-anchor="middle">C₁₂H₂₂O₁₁</text>

  <line x1="360" y1="110" x2="410" y2="110" stroke="#2563eb" stroke-width="2.5" marker-end="url(#arr-flow)"/>
  <text x="385" y="95" font-family="sans-serif" font-size="11" font-weight="bold" fill="#2563eb" text-anchor="middle">Maltase (Yeast)</text>

  <!-- Step 3: Glucose -->
  <rect x="410" y="80" width="140" height="60" fill="#dcfce7" stroke="#16a34a" stroke-width="2" rx="4"/>
  <text x="480" y="105" font-family="sans-serif" font-size="13" font-weight="bold" fill="#15803d" text-anchor="middle">Glucose</text>
  <text x="480" y="125" font-family="sans-serif" font-size="11" fill="#166534" text-anchor="middle">C₆H₁₂O₆</text>

  <!-- Downward arrow to Ethanol -->
  <line x1="480" y1="140" x2="480" y2="200" stroke="#2563eb" stroke-width="2.5" marker-end="url(#arr-flow)"/>
  <text x="510" y="175" font-family="sans-serif" font-size="11" font-weight="bold" fill="#2563eb">Zymase (Yeast)</text>

  <!-- Step 4: Ethanol -->
  <rect x="400" y="200" width="160" height="65" fill="#fce7f3" stroke="#db2777" stroke-width="2.5" rx="4"/>
  <text x="480" y="225" font-family="sans-serif" font-size="14" font-weight="bold" fill="#9d174d" text-anchor="middle">Ethanol + CO₂</text>
  <text x="480" y="245" font-family="sans-serif" font-size="11" fill="#be185d" text-anchor="middle">2 C₂H₅OH + 2 CO₂</text>

  <text x="300" y="325" font-family="sans-serif" font-size="13" font-weight="bold" fill="#0f172a" text-anchor="middle">Esterification: C₂H₅OH + CH₃COOH ⇌ CH₃COOC₂H₅ (Ethyl Ethanoate) + H₂O</text>
  <text x="300" y="350" font-family="sans-serif" font-size="12" fill="#475569" text-anchor="middle">Conc. H₂SO₄ functions as acid catalyst and dehydrating agent shifting equilibrium forward</text>
</svg>
''')

# Update reference json with all diagrams
with open('data/theory/waec_theory_reference.json') as f:
    items = json.load(f)

updated_count = 0
for q in items:
    qid = q['id']
    if qid in diagrams:
        q['diagram_url'] = diagrams[qid]
        updated_count += 1

with open('data/theory/waec_theory_reference.json', 'w') as f:
    json.dump(items, f, indent=2)

print(f"Total diagrams registered: {len(diagrams)}")
print(f"Total questions with diagram_url now in JSON: {updated_count}")
