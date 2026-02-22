import svgPaths from "./svg-czrgecjots";

function LogoGoogleg48Dp() {
  return (
    <div className="absolute left-[0.36px] size-[16.754px] top-[0.36px]" data-name="logo googleg 48dp">
      <svg className="absolute block size-full" fill="none" preserveAspectRatio="none" viewBox="0 0 16.7538 16.7538">
        <g id="logo googleg 48dp">
          <path clipRule="evenodd" d={svgPaths.p13008700} fill="var(--fill-0, #4285F4)" fillRule="evenodd" id="Shape" />
          <path clipRule="evenodd" d={svgPaths.p2e899a00} fill="var(--fill-0, #34A853)" fillRule="evenodd" id="Shape_2" />
          <path clipRule="evenodd" d={svgPaths.p1bd76f80} fill="var(--fill-0, #FBBC05)" fillRule="evenodd" id="Shape_3" />
          <path clipRule="evenodd" d={svgPaths.p2ea14b00} fill="var(--fill-0, #EA4335)" fillRule="evenodd" id="Shape_4" />
          <g id="Shape_5" />
        </g>
      </svg>
    </div>
  );
}

function GoogleLogo() {
  return (
    <div className="bg-white relative shrink-0 size-[17.482px]" data-name="Google Logo">
      <LogoGoogleg48Dp />
    </div>
  );
}

function Frame() {
  return (
    <div className="-translate-x-1/2 -translate-y-1/2 absolute bg-white content-stretch flex gap-[10.926px] items-start left-1/2 p-[10.926px] rounded-[10px] top-1/2">
      <GoogleLogo />
      <p className="font-['Roboto:Medium',sans-serif] font-medium leading-[normal] relative shrink-0 text-[14.57px] text-[rgba(0,0,0,0.54)]" style={{ fontVariationSettings: "\'wdth\' 100" }}>
        Continue with Google
      </p>
    </div>
  );
}

function AppleLogo() {
  return (
    <div className="relative shrink-0 size-[17.482px]" data-name="Apple Logo">
      <svg className="absolute block size-full" fill="none" preserveAspectRatio="none" viewBox="0 0 17.4822 17.4822">
        <g clipPath="url(#clip0_1_157)" id="Apple Logo">
          <rect fill="black" height="17.4822" width="17.4822" />
          <path d={svgPaths.p1bcb9100} fill="var(--fill-0, white)" id="path4" />
        </g>
        <defs>
          <clipPath id="clip0_1_157">
            <rect fill="white" height="17.4822" width="17.4822" />
          </clipPath>
        </defs>
      </svg>
    </div>
  );
}

function Frame1() {
  return (
    <div className="-translate-x-1/2 -translate-y-1/2 absolute bg-black content-stretch flex gap-[10.926px] items-start left-[calc(50%+0.36px)] p-[10.926px] rounded-[10px] top-1/2">
      <AppleLogo />
      <p className="font-['SF_Pro_Display:Medium',sans-serif] leading-[normal] not-italic relative shrink-0 text-[14.57px] text-white">Continue with Apple</p>
    </div>
  );
}

function Frame2() {
  return (
    <div className="-translate-x-1/2 -translate-y-1/2 absolute bg-black content-stretch flex gap-[10.926px] items-start left-[calc(50%+0.36px)] p-[10.926px] rounded-[10px] top-1/2">
      <p className="font-['Share_Tech_Mono:Regular',sans-serif] leading-[normal] not-italic relative shrink-0 text-[#828282] text-[10.61px]">Enter your email...</p>
    </div>
  );
}

function Frame3() {
  return (
    <div className="-translate-x-1/2 -translate-y-1/2 absolute bg-black content-stretch flex gap-[10.926px] items-start left-[calc(50%+0.36px)] p-[10.926px] rounded-[10px] top-1/2">
      <p className="font-['Share_Tech_Mono:Regular',sans-serif] leading-[normal] not-italic relative shrink-0 text-[10.61px] text-white">Continue</p>
    </div>
  );
}

function Group() {
  return (
    <div className="absolute contents left-[38px] top-[79px]">
      <div className="absolute bg-black left-[38px] rounded-[1.714px] size-[6.285px] top-[104.14px]" />
      <div className="absolute bg-black left-[63.71px] rounded-[1.714px] size-[6.285px] top-[147.57px]" />
      <div className="absolute bg-black left-[48.29px] rounded-[1.714px] size-[6.285px] top-[139px]" />
      <div className="absolute bg-[red] left-[96.28px] rounded-[1.714px] size-[6.285px] top-[139px]" />
      <div className="absolute bg-[red] left-[262.69px] rounded-[1.714px] size-[6.285px] top-[136.29px]" />
      <div className="absolute bg-black left-[38px] rounded-[1.714px] size-[6.285px] top-[123px]" />
      <div className="absolute bg-black left-[104.85px] rounded-[1.714px] size-[6.285px] top-[104.71px]" />
      <div className="absolute bg-black left-[104.85px] rounded-[1.714px] size-[6.285px] top-[123.57px]" />
      <div className="absolute bg-black left-[48.29px] rounded-[1.714px] size-[6.285px] top-[89.29px]" />
      <div className="absolute bg-black left-[96.28px] rounded-[1.714px] size-[6.285px] top-[89.29px]" />
      <div className="absolute bg-black left-[63.14px] rounded-[1.714px] size-[6.285px] top-[79px]" />
      <div className="absolute bg-black left-[82px] rounded-[1.714px] size-[6.285px] top-[79px]" />
      <div className="absolute bg-black left-[82.57px] rounded-[1.714px] size-[6.285px] top-[147.57px]" />
    </div>
  );
}

function Logo() {
  return (
    <div className="absolute contents left-[38px] top-[79px]" data-name="logo">
      <Group />
      <p className="absolute font-['NuCore_Condensed:Regular',sans-serif] leading-[60.144px] left-[136.43px] not-italic text-[50.97px] text-black top-[86.7px] tracking-[3.5679px]">agora</p>
    </div>
  );
}

export default function IPhone() {
  return (
    <div className="bg-white relative size-full" data-name="iPhone 17 - 2">
      <div className="absolute bg-white h-[40px] left-[75px] shadow-[0px_0px_2.185px_0px_rgba(0,0,0,0.08),0px_1.457px_2.185px_0px_rgba(0,0,0,0.17)] top-[576px] w-[251px]" data-name="Continue with Google / Centre / Fixed">
        <Frame />
      </div>
      <div className="absolute bg-black h-[40px] left-[75px] shadow-[0px_0px_2.185px_0px_rgba(0,0,0,0.08),0px_1.457px_2.185px_0px_rgba(0,0,0,0.17)] top-[631px] w-[251px]" data-name="Continue with Apple / Centre / Fixed">
        <Frame1 />
      </div>
      <div className="absolute bg-black h-[40px] left-[75px] shadow-[0px_0px_2.185px_0px_rgba(0,0,0,0.08),0px_1.457px_2.185px_0px_rgba(0,0,0,0.17)] top-[723px] w-[251px]" data-name="Continue with Apple / Centre / Fixed">
        <Frame2 />
      </div>
      <div className="absolute bg-black h-[40px] left-[75px] shadow-[0px_0px_2.185px_0px_rgba(0,0,0,0.08),0px_1.457px_2.185px_0px_rgba(0,0,0,0.17)] top-[778px] w-[251px]" data-name="Continue with Apple / Centre / Fixed">
        <Frame3 />
      </div>
      <div className="absolute h-0 left-[75px] top-[694.99px] w-[93.239px]">
        <div className="absolute inset-[-0.73px_0_0_0]">
          <svg className="block size-full" fill="none" preserveAspectRatio="none" viewBox="0 0 93.2386 0.728426">
            <line id="Line 1" stroke="var(--stroke-0, black)" strokeWidth="0.728426" x2="93.2386" y1="0.364213" y2="0.364213" />
          </svg>
        </div>
      </div>
      <div className="absolute h-0 left-[233.07px] top-[694.99px] w-[93.239px]">
        <div className="absolute inset-[-0.73px_0_0_0]">
          <svg className="block size-full" fill="none" preserveAspectRatio="none" viewBox="0 0 93.2386 0.728426">
            <line id="Line 1" stroke="var(--stroke-0, black)" strokeWidth="0.728426" x2="93.2386" y1="0.364213" y2="0.364213" />
          </svg>
        </div>
      </div>
      <p className="absolute font-['NuCore_Condensed:Regular',sans-serif] leading-[normal] left-[187.91px] not-italic text-[14.569px] text-black top-[686.25px]">OR</p>
      <Logo />
      <p className="-translate-x-1/2 absolute font-['Share_Tech_Mono:Regular',sans-serif] h-[309px] leading-[60.144px] left-[calc(50%+0.5px)] not-italic text-[32px] text-black text-center top-[calc(50%-227px)] tracking-[2.24px] w-[265px] whitespace-pre-wrap">Refine your judgment through controlled divergence_</p>
    </div>
  );
}