import { Routes, Route, Navigate } from "react-router-dom";
import CreatorShell from "./CreatorShell";
import Gallery from "./pages/Gallery";
import Share from "./pages/Share";
import Legal from "./pages/Legal";
import TextToSpeech from "./pages/TextToSpeech";
import ApiDocs from "./pages/ApiDocs";
import VideoShare from "./pages/VideoShare";
import Studio from "./pages/Studio";
import SpeechToSpeech from "./pages/SpeechToSpeech";
import VoiceClone from "./pages/VoiceClone";
import Studio3D from "./pages/Studio3D";
import ModelShare from "./pages/ModelShare";
import Spaces from "./pages/Spaces";
import SpaceEditor from "./pages/SpaceEditor";
import SpaceView from "./pages/SpaceView";
import AboutLuchii from "./pages/AboutLuchii";
import LuchiiAgent from "./pages/LuchiiAgent";

const PAGES = [
  ["gallery", <Gallery />], ["tts", <TextToSpeech />], ["developers", <ApiDocs />], ["legal/:doc", <Legal />],
  ["s/:id", <Share />], ["video", <Studio kind="video" />], ["v/:id", <VideoShare />], ["audio", <Studio kind="music" />],
  ["sts", <SpeechToSpeech />], ["voice-clone", <VoiceClone />], ["3d", <Studio3D />], ["3d/s/:id", <ModelShare />],
  ["spaces", <Spaces />], ["spaces/:id", <SpaceEditor />], ["spaces/:id/view", <SpaceView />],
  ["agent", <LuchiiAgent />], ["about-luchii", <AboutLuchii />],
];

export default function CreatorRoutes() {
  return (
    <Routes>
      {PAGES.map(([path, el]) => (
        <Route key={path} path={path} element={<CreatorShell active="tools">{el}</CreatorShell>} />
      ))}
      <Route path="*" element={<Navigate to="/create" replace />} />
    </Routes>
  );
}
