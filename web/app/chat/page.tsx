import type { Metadata } from "next";
import ChatApp from "@/components/chat/ChatApp";

export const metadata: Metadata = {
  title: "Workbench — Ask your PDFs",
  description:
    "Upload documents and ask questions. Watch the agent retrieve, grade, and rewrite — every answer cited and grounded.",
};

export default function ChatPage() {
  return <ChatApp />;
}
