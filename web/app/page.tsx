import Hero from "@/components/landing/Hero";
import PipelineWalkthrough from "@/components/landing/PipelineWalkthrough";
import TechFootnotes from "@/components/landing/TechFootnotes";
import Cta from "@/components/landing/Cta";

/**
 * Landing page — a scroll-driven editorial explainer of the RAG pipeline.
 * Fully static: no API calls, prerendered at build time.
 */
export default function Home() {
  return (
    <main className="flex-1">
      <Hero />
      <PipelineWalkthrough />
      <TechFootnotes />
      <Cta />
    </main>
  );
}
