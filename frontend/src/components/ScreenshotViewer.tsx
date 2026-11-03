import { useState } from "react";
import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { Button, Dialog } from "./ui";

/** Zoomable image viewer for incident evidence. */
export default function ScreenshotViewer({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  const [zoom, setZoom] = useState(1);
  return (
    <Dialog open onClose={onClose} wide title={alt}
      footer={
        <div className="flex w-full items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))} aria-label="Zoom out"><ZoomOut className="h-4 w-4" /></Button>
          <span className="w-12 text-center text-xs tabular-nums">{Math.round(zoom * 100)}%</span>
          <Button size="sm" variant="outline" onClick={() => setZoom((z) => Math.min(4, z + 0.25))} aria-label="Zoom in"><ZoomIn className="h-4 w-4" /></Button>
          <Button size="sm" variant="ghost" onClick={() => setZoom(1)}><Maximize2 className="h-4 w-4" />Fit</Button>
          <a href={src} target="_blank" rel="noreferrer" className="ml-auto text-xs text-primary hover:underline">Open original</a>
        </div>
      }>
      <div className="overflow-auto rounded-md bg-muted/50" style={{ maxHeight: "60vh" }}>
        <img src={src} alt={alt} style={{ width: `${zoom * 100}%`, maxWidth: "none" }} className="mx-auto block" />
      </div>
    </Dialog>
  );
}
