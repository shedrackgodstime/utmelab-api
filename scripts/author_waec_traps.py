#!/usr/bin/env python3
"""Write the WAEC traps for the chapters whose WAEC packs report none.

    python3 scripts/author_waec_traps.py

A trap is a mistake candidates make, with the correction and the evidence
behind it. The JAMB traps for the newer Physics chapters were written first;
these are the same traps seen from the WAEC side, each one tied to a WAEC
recall check that offers the wrong reading as an option.

The evidence is our own question, so the trap's status is `candidate`: it
waits for a paper question that shows the same mistake before it is called
proven. The validator refuses a trap that claims a paper without citing one.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "data/chapter-specs"


def trap(tid, exam, section, misconception, correction, signal, check_id):
    return {
        "id": tid,
        "exam": exam,
        "subject": "physics",
        "section_id": section,
        "misconception": misconception,
        "correction": correction,
        "signal": signal,
        "status": "candidate",
        "paper_evidence": {
            "check_id": check_id,
            "exam": exam,
            "year": None,
            "source": "authored",
        },
        "frequency": "candidate",
    }


#: The WAEC traps, keyed by chapter id. Each is tied to a WAEC recall check
#: in the same chapter, and the check is where the mistake shows.
TRAPS: dict[str, list[dict]] = {
    "phy_atomic_physics": [
        trap("trap-3", "WAEC", "sec-2",
             "The atom was first shown to have a nucleus by J. J. Thomson.",
             "It was Rutherford, from the gold foil experiment. Thomson's model had the positive charge spread through the atom, and the scattering of the fast alpha particles was what showed the mass was concentrated in a tiny nucleus.",
             "Our own question offers Thomson as the answer.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-4",
             "The energy of an electron in the ground state of the hydrogen atom is zero.",
             "It is negative, because the electron is bound to the nucleus. It takes a positive amount of energy, the ionisation energy, to free it, which is why the bound states sit below zero.",
             "Our own question offers zero as an option.",
             "rc-2"),
    ],
    "phy_dc_circuits": [
        trap("trap-3", "WAEC", "sec-2",
             "Resistances in parallel add, so $6\\,\\Omega$ and $3\\,\\Omega$ in parallel give $9\\,\\Omega$.",
             "Adding the resistances is the rule for a series connection. In parallel the reciprocals add, so $\\frac{1}{R} = \\frac{1}{6} + \\frac{1}{3} = \\frac{1}{2}$ and the combination is $2\\,\\Omega$.",
             "Our own question offers the series answer for the parallel case.",
             "rc-2"),
        trap("trap-4", "WAEC", "sec-4",
             "Kirchhoff's loop rule says that the current is the same everywhere round a circuit.",
             "That is the junction rule, and it is about current at a node. The loop rule is about potential differences: the sum of the changes in potential round any closed loop is zero.",
             "Our own question offers the junction rule as the answer.",
             "rc-4"),
    ],
    "phy_electric_charge_and_field": [
        trap("trap-3", "WAEC", "sec-2",
             "Rubbing an isolated body leaves it with a net charge.",
             "Charge is conserved. Rubbing moves charge from one part of the body to another, so the total charge of an isolated body stays zero even though its parts are now charged.",
             "Our own question asks what the total charge of an isolated body is.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-4",
             "The electrostatic force between two charges is inversely proportional to the distance between them.",
             "It is inversely proportional to the square of the distance, so doubling the separation makes the force a quarter as large.",
             "Our own question offers the inverse-distance law as an option.",
             "rc-3"),
    ],
    "phy_electric_current": [
        trap("trap-3", "WAEC", "sec-3",
             "The potential difference across a resistor of $10\\,\\Omega$ carrying $2\\,\\text{A}$ is $5\\,\\text{V}$.",
             "Ohm's law gives $V = IR = 2 \\times 10 = 20\\,\\text{V}$. The resistance and the current multiply; the answer is not the current divided by the resistance.",
             "Our own question offers the halved reading as an option.",
             "rc-2"),
        trap("trap-4", "WAEC", "sec-5",
             "The SI unit of electrical power is the joule.",
             "Power is measured in watts, one joule per second. The joule is the unit of energy, and power is the rate at which energy is used.",
             "Our own question asks for the unit of power.",
             "rc-3"),
    ],
    "phy_electric_potential": [
        trap("trap-3", "WAEC", "sec-2",
             "Potential difference between two points is the force on a unit charge placed between them.",
             "That is the electric field. The potential difference is the work done per unit charge in moving a charge between the two points.",
             "Our own question offers the field definition as an option.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-4",
             "The potential of a point charge falls with the square of the distance, like the field.",
             "The potential falls as $1/r$. It is the electric field that falls as $1/r^2$, because the field is the gradient of the potential.",
             "Our own question offers the square law as an option.",
             "rc-3"),
    ],
    "phy_em_induction_and_ac": [
        trap("trap-3", "WAEC", "sec-3",
             "Faraday's law says the induced emf is proportional to the magnetic flux itself.",
             "It is proportional to the rate of change of the flux, so a steady flux induces nothing at all. The minus sign in Lenz's law is what says the induced current opposes the change.",
             "Our own question offers the flux itself as an option.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-3",
             "The induced current flows so as to reinforce the magnetic field that caused it.",
             "It opposes the change that produced it, which is how the conservation of energy shows up in induction. A current that reinforced the field would give away energy for nothing.",
             "Our own question offers the reinforcing direction as an option.",
             "rc-2"),
    ],
    "phy_em_waves": [
        trap("trap-3", "WAEC", "sec-4",
             "The electromagnetic spectrum is arranged in order of increasing wavelength.",
             "It runs from radio waves to gamma rays, so the frequency increases as the wavelength decreases. The speed of every one of them in vacuum is the same.",
             "Our own question offers the wavelength ordering as an option.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-5",
             "The energy of an electromagnetic wave depends on how bright it is.",
             "The energy of a photon is set by its frequency, $E = hf$. Brightness tells you how many photons arrive, not how much energy each one carries.",
             "Our own question offers the brightness reading as an option.",
             "rc-2"),
    ],
    "phy_fluid_statics": [
        trap("trap-3", "WAEC", "sec-5",
             "The pressure at depth $h$ in a fluid is $\\rho g h$ below atmospheric pressure.",
             "The gauge pressure at depth $h$ is $\\rho gh$, and the absolute pressure is that plus atmospheric. The pressure rises with depth, so a deeper point is at a higher pressure, not a lower one.",
             "Our own question offers the pressure below atmospheric as an option.",
             "rc-2"),
        trap("trap-4", "WAEC", "sec-7",
             "Gauge pressure is the total pressure in the fluid.",
             "Gauge pressure is the pressure in excess of atmospheric, so a gauge reading of zero means the pressure is atmospheric. The absolute pressure is the gauge pressure plus atmospheric.",
             "Our own question offers the total pressure as an option.",
             "rc-3"),
    ],
    "phy_geometric_optics": [
        trap("trap-3", "WAEC", "sec-3",
             "The law of reflection says the angle of reflection equals the angle of incidence, both measured from the surface.",
             "Both angles are measured from the normal, the line perpendicular to the surface at the point of incidence. Measuring from the surface gives a different pair of numbers, though the two are complementary.",
             "Our own question asks which angle the reflection angle equals.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-4",
             "Snell's law relates the angles of incidence and refraction to the wavelengths in the two media.",
             "It relates them to the speeds of light, through the refractive indices. The wavelengths change as the speed changes, and the frequency does not, which is the point of the law.",
             "Our own question offers the wavelength reading as an option.",
             "rc-2"),
    ],
    "phy_heat_transfer": [
        trap("trap-3", "WAEC", "sec-4",
             "The temperature of a liquid rises steadily while it boils away.",
             "It stays at the boiling point until the liquid has gone. The heat supplied goes into the latent heat of vaporisation, breaking the bonds between molecules rather than raising the temperature.",
             "Our own question offers the steady rise as an option.",
             "rc-2"),
        trap("trap-4", "WAEC", "sec-6",
             "Conduction is the transfer of heat by the movement of the heated substance.",
             "Conduction is by collisions between neighbouring particles, without the substance moving. The bulk movement of a heated fluid is convection, which is a different mechanism.",
             "Our own question offers the movement reading as an option.",
             "rc-3"),
    ],
    "phy_magnetism": [
        trap("trap-3", "WAEC", "sec-2",
             "Like poles of a magnet attract each other.",
             "Like poles repel and unlike poles attract. That is the first law of magnetism, and it is the same pattern as the repulsion between like electric charges.",
             "Our own question offers attraction as the answer.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-5",
             "The force on a charged particle in a magnetic field does not depend on the speed of the particle.",
             "It does, because the force is $F = qvB\\sin\\theta$. A stationary charge in a magnetic field feels no magnetic force at all, and the force grows with the speed.",
             "Our own question offers the speed-independent reading as an option.",
             "rc-2"),
    ],
    "phy_oscillations_and_waves": [
        trap("trap-3", "WAEC", "sec-3",
             "The frequency of an oscillation is the time taken for one complete cycle.",
             "That is the period. The frequency is the number of cycles in one second, and the two are reciprocals, so a wave of $50\\,\\text{Hz}$ has a period of $0.02\\,\\text{s}$.",
             "Our own question offers the period as the frequency.",
             "rc-2"),
        trap("trap-4", "WAEC", "sec-3",
             "A wave of frequency $50\\,\\text{Hz}$ has a period of $2\\,\\text{s}$.",
             "The period is the reciprocal of the frequency, $T = 1/f = 1/50 = 0.02\\,\\text{s}$. Multiplying the two instead of dividing gives the wrong figure.",
             "Our own question offers the multiplied reading as an option.",
             "rc-3"),
    ],
    "phy_physics_of_hearing": [
        trap("trap-3", "WAEC", "sec-2",
             "Sound is a transverse wave, like light.",
             "In sound the particles of the medium oscillate along the direction of travel, so the wave is longitudinal. Light is transverse, and the difference is what makes sound need a medium and light not.",
             "Our own question offers transverse as the answer.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-3",
             "The speed of sound in air is about $1500\\,\\text{m/s}$.",
             "In air at room temperature it is about $340\\,\\text{m/s}$. The figure near $1500\\,\\text{m/s}$ belongs to sound in water, and $3 \\times 10^8\\,\\text{m/s}$ is the speed of light.",
             "Our own question offers the speed in water as an option.",
             "rc-2"),
    ],
    "phy_quantum_physics": [
        trap("trap-3", "WAEC", "sec-2",
             "The energy of a photon is proportional to its wavelength.",
             "It is proportional to its frequency, $E = hf$, so a longer wavelength means a lower energy. This is why the blue end of the spectrum carries more energy per photon than the red end.",
             "Our own question offers the wavelength reading as an option.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-3",
             "The kinetic energy of the electrons emitted in the photoelectric effect is set by the intensity of the light.",
             "It is set by the frequency, $K = hf - \\phi$. The intensity decides how many electrons come out, not how fast they are, which is the observation that told Bohr the light was quantised.",
             "Our own question offers the intensity reading as an option.",
             "rc-2"),
    ],
    "phy_radioactivity": [
        trap("trap-3", "WAEC", "sec-6",
             "The half-life of a radioactive sample is the time in which all of it decays.",
             "It is the time in which half the nuclei decay. The sample never decays completely in a finite time, and the same half-life applies however much you start with.",
             "Our own question offers the full decay as an option.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-5",
             "In alpha decay the nucleus emits an electron.",
             "It emits a helium nucleus, made of two protons and two neutrons, and the atomic number falls by two. The electron is the beta particle, emitted in beta decay instead.",
             "Our own question offers the electron as an option.",
             "rc-2"),
    ],
    "phy_rotational_motion": [
        trap("trap-3", "WAEC", "sec-3",
             "Angular velocity is measured in revolutions per second.",
             "It is measured in radians per second. Revolutions per second is the frequency of the rotation, which is the same thing only because a revolution is $2\\pi$ radians.",
             "Our own question offers revolutions as the answer.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-4",
             "The rotational inertia of a solid disc about its central axis is $MR^2$.",
             "It is $\\frac{1}{2}MR^2$. The hoop, which has all its mass at the rim, is the one with $MR^2$, and a disc with the same mass and radius is harder to start turning.",
             "Our own question offers the hoop value as an option.",
             "rc-2"),
    ],
    "phy_special_relativity": [
        trap("trap-3", "WAEC", "sec-2",
             "The speed of light in vacuum is different for observers moving at different speeds.",
             "It is the same for every inertial observer, whatever the motion of the source or the observer. That is Einstein's second postulate, and it is why there is no absolute rest.",
             "Our own question offers the observer-dependent reading as an option.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-3",
             "A clock moving at a high speed ticks faster for an observer who sees it moving.",
             "It ticks more slowly. Time dilation means the moving clock runs slow as measured in the frame in which it is moving, and each of two inertial observers sees the other's clock run slow.",
             "Our own question offers the faster reading as an option.",
             "rc-2"),
    ],
    "phy_vision_and_instruments": [
        trap("trap-3", "WAEC", "sec-3",
             "A short-sighted person is given a diverging lens to correct their sight.",
             "They are given a converging lens. A short-sighted eye focuses distant light in front of the retina, and a converging lens brings the focus back onto it, which lets the wearer see near objects.",
             "Our own question offers the diverging lens as the answer.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-5",
             "The magnifying power of a compound microscope is increased by using an eyepiece of longer focal length.",
             "A shorter eyepiece focal length gives a larger angular magnification, because the eyepiece acts as a simple magnifier. A longer objective focal length helps as well.",
             "Our own question offers the longer eyepiece as an option.",
             "rc-2"),
    ],
    "phy_wave_optics": [
        trap("trap-3", "WAEC", "sec-4",
             "The fringe spacing in Young's double slit experiment is inversely proportional to the wavelength.",
             "It is directly proportional to the wavelength and inversely proportional to the slit separation, since the spacing is $\\frac{\\lambda L}{d}$. A longer wavelength gives wider fringes.",
             "Our own question offers the inverse reading as an option.",
             "rc-1"),
        trap("trap-4", "WAEC", "sec-3",
             "Huygens' principle says that light travels in straight lines through a medium.",
             "It says every point on a wavefront acts as a source of secondary wavelets, and the later wavefront is their envelope. That is what lets light bend round an obstacle, which is diffraction.",
             "Our own question offers the reflector as an option.",
             "rc-2"),
    ],
}


def main() -> int:
    written = 0
    missing: list[str] = []
    for chapter_id, traps in sorted(TRAPS.items()):
        path = SPECS / f"{chapter_id}.json"
        if not path.exists():
            missing.append(chapter_id)
            continue
        spec = json.loads(path.read_text())
        existing = spec.get("exam_traps", [])
        kept = [item for item in existing if item["exam"] != "WAEC"]
        spec["exam_traps"] = kept + traps
        path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
        written += 1

    if missing:
        print(f"no spec for {len(missing)} chapters: {', '.join(missing)}")
        return 1
    total = sum(len(traps) for traps in TRAPS.values())
    print(f"wrote WAEC traps for {written} chapters: {total} traps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
