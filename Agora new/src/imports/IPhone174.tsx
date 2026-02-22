function Frame() {
  return (
    <div className="-translate-x-1/2 -translate-y-1/2 absolute bg-black content-stretch flex gap-[10.926px] items-start left-[calc(50%+0.36px)] p-[10.926px] rounded-[10px] top-1/2">
      <p className="font-['Share_Tech_Mono:Regular',sans-serif] leading-[normal] not-italic relative shrink-0 text-[#828282] text-[10.61px]">Enter your nickname...</p>
    </div>
  );
}

function Frame1() {
  return (
    <div className="-translate-x-1/2 -translate-y-1/2 absolute bg-black content-stretch flex gap-[10.926px] items-start left-[calc(50%+0.36px)] p-[10.926px] rounded-[10px] top-1/2">
      <p className="font-['Share_Tech_Mono:Regular',sans-serif] leading-[normal] not-italic relative shrink-0 text-[10.61px] text-white">Continue</p>
    </div>
  );
}

export default function IPhone() {
  return (
    <div className="bg-white relative size-full" data-name="iPhone 17 - 4">
      <div className="absolute bg-black h-[40px] left-[71px] shadow-[0px_0px_2.185px_0px_rgba(0,0,0,0.08),0px_1.457px_2.185px_0px_rgba(0,0,0,0.17)] top-[721px] w-[251px]" data-name="Continue with Apple / Centre / Fixed">
        <Frame />
      </div>
      <div className="absolute bg-black h-[40px] left-[71px] shadow-[0px_0px_2.185px_0px_rgba(0,0,0,0.08),0px_1.457px_2.185px_0px_rgba(0,0,0,0.17)] top-[776px] w-[251px]" data-name="Continue with Apple / Centre / Fixed">
        <Frame1 />
      </div>
    </div>
  );
}