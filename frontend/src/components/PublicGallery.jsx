import React from "react";
import { Link } from "react-router-dom";

export default function PublicGallery({ items, titleFor }) {
  if (!items.length) return null;
  return (
    <section id="public-gallery" data-testid="public-gallery" className="max-w-[1400px] mx-auto px-5 md:px-8 pb-20 scroll-mt-24">
      <span className="text-xs font-semibold uppercase tracking-widest text-[#00F0FF]">Public gallery</span>
      <h2 className="font-display font-bold tracking-tight text-2xl md:text-4xl mt-3 mb-8">Fresh from the community</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {items.map((g) => (
          <Link key={g.id} to={`/s/${g.id}`} data-testid={`public-gallery-card-${g.id}`}
            className="group relative block aspect-square rounded-xl overflow-hidden ring-1 ring-white/10 hover:ring-[#00F0FF]/60 transition">
            <img src={g.image_base64} alt={g.prompt} loading="lazy"
              className="w-full h-full object-cover group-hover:scale-[1.04] transition-transform duration-500" />
            <span className="absolute inset-x-0 bottom-0 p-2 text-xs font-semibold bg-gradient-to-t from-black/90 to-transparent truncate">
              {titleFor(g.prompt)}
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
