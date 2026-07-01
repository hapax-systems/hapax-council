w05
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map w05
		rgbgen const 1.0 1.0 1.0
	}
}

ward_atlas
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map ward_atlas
		rgbgen const 0.72 0.72 0.78
	}
}

w18
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map w18
		rgbgen const 1.0 1.0 1.0
	}
}

w19
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map w19
		rgbgen const 1.0 1.0 1.0
	}
}

w09
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map w09
		rgbgen const 0.72 0.72 0.78
	}
}

w22
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map w22
		rgbgen const 0.72 0.72 0.78
	}
}

w27
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map w27
		rgbgen const 0.72 0.72 0.78
	}
}

w35
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map w35
		rgbgen const 1.0 1.0 1.0
	}
}

cam_bop
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map cam_bop
		rgbgen const 0.72 0.72 0.78
	}
}

cam_brm
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map cam_brm
		rgbgen const 0.72 0.72 0.78
	}
}

cam_bsy
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map cam_bsy
		rgbgen const 0.72 0.72 0.78
	}
}

cam_cdk
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map cam_cdk
		rgbgen const 0.72 0.72 0.78
	}
}

cam_crm
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map cam_crm
		rgbgen const 0.72 0.72 0.78
	}
}

cam_cov
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map cam_cov
		rgbgen const 0.72 0.72 0.78
	}
}

speech_wave
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map speech_wave
		rgbgen const 0.72 0.72 0.78
	}
}

// Operator 2026-06-20: the OARB sphere had NO shader entry -> default lit model
// rendering washed/iridesced the live YT. Give it the same clean, unlit treatment
// the ward surfaces get so the canonical-playlist video is legible on the sphere.
progs/aoa_sphere.mdl_0
{
	surfaceparm nolightmap
	surfaceparm nomarks
	surfaceparm nonsolid
	dpnoshadow
	dpnortlight
	{
		map progs/aoa_sphere.mdl_0
		rgbgen const 1.0 1.0 1.0
	}
}
