import React, { useState } from "react";

const slugOf = (name) => name.toLowerCase().replace(/\s+/g, "-");

export default function ModelSamples({ m }) {
  const all = [m.img, m.img.replace(/\.jpg$/, "-2.jpg"), m.img.replace(/\.jpg$/, "-3.jpg")];
  const [broken, setBroken] = useState([]);
  const [active, setActive] = useState(0);
  const samples = all.filter((s) => !broken.includes(s));
  const current = samples[Math.min(active, samples.length - 1)] || m.img;
  const slug = slugOf(m.name);
  return (
    <>
      <img src={current} alt={`${m.name} sample output`} data-testid={`model-sample-main-${slug}`}
        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700" />
      <div className="absolute bottom-2.5 right-2.5 z-10 flex gap-1.5" data-testid={`model-samples-${slug}`}>
        {all.map((s) => (
          <button key={s} type="button" onClick={() => setActive(samples.indexOf(s))}
            data-testid={`model-sample-thumb-${slug}-${all.indexOf(s)}`} aria-label="Show sample"
            className={`${broken.includes(s) ? "hidden" : ""} w-11 h-8 rounded-md overflow-hidden ring-2 transition ${s === current ? "ring-[#00F0FF]" : "ring-white/20 opacity-75 hover:opacity-100"}`}>
            <img src={s} alt="" loading="lazy" className="w-full h-full object-cover"
              onError={() => setBroken((b) => (b.includes(s) ? b : [...b, s]))} />
          </button>
        ))}
      </div>
    </>
  );
}
