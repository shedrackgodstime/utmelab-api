import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

// Starlight docs collection (guides only for now).
export const collections = {
  docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
};
